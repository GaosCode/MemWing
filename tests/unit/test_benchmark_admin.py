from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.application.long_term_filter_service import LongTermFilterService
from memwing.application.remember_event_records import outbox_job
from memwing.core.memory_search import MemorySearchResult, MemorySearchResultItem
from memwing.core.models import LongTermFilterItem, OutboxJob, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.db.in_memory_benchmark_admin import InMemoryBenchmarkAdminStore
from memwing.ports.benchmark_admin import BenchmarkRuntimeBinding, BenchmarkScope
from memwing.ports.llm_filter import LongTermFilterRequest
from memwing.workers.benchmark_drain import BenchmarkDrainWorker
from memwing.workers.derived_outbox_worker import DerivedOutboxWorker


def test_cleanup_scope_refuses_non_benchmark_project() -> None:
    async def run() -> None:
        service = _service(InMemoryDataStore(), _EvidenceIndex())

        with pytest.raises(ValueError, match="benchmark:"):
            await service.cleanup_scope(
                scope=BenchmarkScope(
                    project_memory_space_id="project_001",
                    group_id="group_001",
                    thread_id="thread_001",
                    shared_group_id=None,
                ),
                runtime_binding=_runtime_binding(),
            )

    asyncio.run(run())


def test_readiness_distinguishes_unavailable_backend_from_empty_results() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        evidence = _UnavailableEvidenceIndex()
        service = _service(store, evidence)
        scope = BenchmarkScope(
            project_memory_space_id="benchmark:run:case",
            group_id="benchmark:case",
            thread_id="benchmark:case",
            shared_group_id=None,
        )
        await service.cleanup_scope(scope=scope, runtime_binding=_runtime_binding())

        result = await service.readiness(
            scope=scope,
            expected_source_event_ids=(),
            queries=("负责人是谁？",),
        )

        assert result.ready is False
        assert result.backends["unavailable"] == {"evidence_index": 1}
        assert result.queries[0]["result_count"] == 0
        assert result.evidence["ready"] is False
        assert result.warnings[0]["branch"] == "evidence_index"

    asyncio.run(run())


def test_drain_indexes_evidence_and_marks_outbox_succeeded() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        evidence = _EvidenceIndex()
        service = _service(store, evidence)
        scope = BenchmarkScope(
            project_memory_space_id="benchmark:run:case",
            group_id="benchmark:case",
            thread_id="benchmark:case",
            shared_group_id=None,
        )
        await service.cleanup_scope(scope=scope, runtime_binding=_runtime_binding())
        async with store.transaction() as tx:
            source, _ = await tx.source_events.insert_if_absent(_source_event(scope))

            await tx.outbox_jobs.enqueue(
                outbox_job(
                    source_event=source,
                    job_type="evidence.index_source_event",
                    now=source.created_at,
                )
            )

        drain = await service.drain_scope(scope=scope, max_iterations=3, batch_size=2)
        readiness = await service.readiness(
            scope=scope,
            expected_source_event_ids=("source_001",),
            queries=("沈南",),
        )

        assert drain.drained is True
        assert drain.outbox_succeeded == 1
        assert drain.evidence_indexed_source_events == 1
        assert drain.pending_outbox_jobs == 0
        assert drain.pending_graph_write_jobs == 0
        assert evidence.indexed_source_event_ids == ["source_001"]
        assert readiness.ready is True
        assert readiness.postgres["source_events"] == 1
        assert readiness.evidence["ready"] is True
        assert readiness.evidence["matched_source_event_ids"] == ("source_001",)
        assert readiness.page_memory == {"ready": False, "count": 0}
        assert readiness.memory_items == {"count": 0}
        assert readiness.queries[0]["source_mix"] == {"evidence_index": 1}
        assert readiness.queries[0]["evidence"]["ready"] is True

    asyncio.run(run())


def test_drain_coalesces_scope_level_outbox_handlers() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        long_term_filter = _RecordingLongTermFilter()
        page_memory_worker = _RecordingPageMemoryWorker()
        benchmark_scope = BenchmarkScope(
            project_memory_space_id="benchmark:run:case",
            group_id="benchmark:case",
            thread_id="benchmark:case",
            shared_group_id=None,
        )
        effective_scope = _effective_scope(benchmark_scope)
        source_events = (
            _source_event(
                benchmark_scope,
                event_id="source_001",
                content="云帆看板负责人是沈南。",
                raw_payload_hash="hash_001",
                runtime_key="runtime_001",
            ),
            _source_event(
                benchmark_scope,
                event_id="source_002",
                content="云帆看板截止日期是五月十五日。",
                raw_payload_hash="hash_002",
                runtime_key="runtime_002",
            ),
        )
        async with store.transaction() as tx:
            for source_event in source_events:
                source, _ = await tx.source_events.insert_if_absent(source_event)
                for job_type in ("page_memory.maybe_rebuild", "long_term_filter.classify"):
                    await tx.outbox_jobs.enqueue(
                        outbox_job(
                            source_event=source,
                            job_type=job_type,
                            now=source.created_at,
                        )
                    )

        drain_worker = BenchmarkDrainWorker(
            store,
            evidence_index=None,
            long_term_filter=LongTermFilterService(
                store,
                long_term_filter,
                lifecycle_transition=LifecycleTransitionService(store),
            ),
            page_memory_worker=page_memory_worker,
            graph_write_worker=None,
        )

        result = await drain_worker.drain_scope(
            scope=effective_scope,
            max_iterations=3,
            batch_size=10,
        )

        assert result.drained is True
        assert result.outbox_succeeded == 4
        assert result.pending_outbox_jobs == 0
        assert len(page_memory_worker.jobs) == 1
        assert len(long_term_filter.requests) == 1
        assert tuple(event.id for event in long_term_filter.requests[0].source_events) == (
            "source_001",
            "source_002",
        )

    asyncio.run(run())


def test_derived_outbox_scope_handlers_only_claim_matching_aggregate_key() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        long_term_filter = _RecordingLongTermFilter()
        benchmark_scope = BenchmarkScope(
            project_memory_space_id="benchmark:run:case",
            group_id="benchmark:case",
            thread_id="thread_001",
            shared_group_id=None,
        )
        other_scope = BenchmarkScope(
            project_memory_space_id="benchmark:run:case",
            group_id="benchmark:case",
            thread_id="thread_002",
            shared_group_id=None,
        )
        async with store.transaction() as tx:
            for source_event in (
                _source_event(
                    benchmark_scope,
                    event_id="source_001",
                    raw_payload_hash="hash_001",
                    runtime_key="runtime_001",
                    thread_id="thread_001",
                ),
                _source_event(
                    other_scope,
                    event_id="source_002",
                    raw_payload_hash="hash_002",
                    runtime_key="runtime_002",
                    thread_id="thread_002",
                ),
            ):
                source, _ = await tx.source_events.insert_if_absent(source_event)
                await tx.outbox_jobs.enqueue(
                    outbox_job(
                        source_event=source,
                        job_type="long_term_filter.classify",
                        now=source.created_at,
                    )
                )

        worker = DerivedOutboxWorker(
            store,
            evidence_index=None,
            long_term_filter=LongTermFilterService(
                store,
                long_term_filter,
                lifecycle_transition=LifecycleTransitionService(store),
            ),
            page_memory_worker=None,
            worker_id="derived_outbox",
        )

        result = await worker.run_once(scope=_effective_scope(benchmark_scope))

        assert result.claimed == 1
        assert result.succeeded == 1
        assert len(long_term_filter.requests) == 1
        assert tuple(event.id for event in long_term_filter.requests[0].source_events) == (
            "source_001",
        )
        assert {job.source_event_id: job.status for job in store.outbox_jobs} == {
            "source_001": "succeeded",
            "source_002": "pending",
        }

    asyncio.run(run())


def _service(store: InMemoryDataStore, evidence) -> BenchmarkAdminService:
    return BenchmarkAdminService(
        unit_of_work=store,
        admin_store=InMemoryBenchmarkAdminStore(store),
        drain_worker=BenchmarkDrainWorker(
            store,
            evidence_index=evidence,
            long_term_filter=LongTermFilterService(
                store,
                _NoopLongTermFilter(),
                lifecycle_transition=LifecycleTransitionService(store),
            ),
            page_memory_worker=None,
            graph_write_worker=None,
        ),
        graph_backend=None,
        evidence_index=evidence,
    )


def _runtime_binding() -> BenchmarkRuntimeBinding:
    return BenchmarkRuntimeBinding(
        runtime="openclaw",
        agent_id="main",
        workspace_id="workspace_001",
        session_id="benchmark:case",
    )


def _effective_scope(scope: BenchmarkScope) -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id=scope.project_memory_space_id,
        group_ids=(scope.group_id,) if scope.group_id is not None else None,
        thread_id=scope.thread_id,
        shared_group_id=scope.shared_group_id,
        safe_mode_enabled=scope.group_id is not None,
        cross_group_allowed=scope.group_id is None,
    )


def _source_event(
    scope: BenchmarkScope,
    *,
    event_id: str = "source_001",
    content: str = "云帆看板负责人是沈南。",
    raw_payload_hash: str = "hash_001",
    runtime_key: str = "runtime_001",
    thread_id: str | None = None,
) -> SourceEvent:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    return SourceEvent(
        id=event_id,
        project_memory_space_id=scope.project_memory_space_id,
        group_id=scope.group_id,
        thread_id=thread_id or scope.thread_id,
        shared_group_id=scope.shared_group_id,
        author_id=None,
        author_name=None,
        source_type="agent_runtime.message_ingested",
        content=content,
        content_preview=content,
        source_url=None,
        event_time=now,
        raw_payload_hash=raw_payload_hash,
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=now,
        runtime_event_idempotency_key=runtime_key,
    )


class _EvidenceIndex:
    def __init__(self) -> None:
        self._events: list[SourceEvent] = []

    @property
    def indexed_source_event_ids(self) -> list[str]:
        return [event.id for event in self._events]

    async def index_source_event(self, source_event: SourceEvent, scope: EffectiveScope) -> None:
        self._events.append(source_event)

    async def search(self, query) -> MemorySearchResult:
        results = tuple(
            MemorySearchResultItem(
                id=f"evidence:{event.id}",
                text=event.content,
                score=1.0,
                source="evidence_index",
                source_event_ids=(event.id,),
                memory_item_ids=(),
                valid_from=event.event_time,
                valid_to=None,
                metadata={},
            )
            for event in self._events
            if query.query in event.content
            and event.project_memory_space_id == query.scope.project_memory_space_id
        )
        return MemorySearchResult(
            contexts=tuple(item.text for item in results),
            results=results,
            next_cursor=None,
            trace_id=query.trace_id or "trace",
        )


class _UnavailableEvidenceIndex(_EvidenceIndex):
    async def search(self, query) -> MemorySearchResult:
        raise RuntimeError("qdrant unavailable")


class _NoopLongTermFilter:
    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        return ()


class _RecordingLongTermFilter(_NoopLongTermFilter):
    def __init__(self) -> None:
        self.requests: list[LongTermFilterRequest] = []

    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        self.requests.append(request)
        return ()


class _RecordingPageMemoryWorker:
    def __init__(self) -> None:
        self.jobs: list[str] = []

    async def maybe_rebuild(self, job: OutboxJob) -> None:
        self.jobs.append(job.id)
