from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime

from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.application.long_term_filter_service import LongTermFilterService
from memwing.application.remember_event_records import outbox_job
from memwing.core.models import LongTermFilterItem, SourceEvent
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.llm_filter import LongTermFilterRequest
from memwing.workers.derived_outbox_worker import DerivedOutboxWorker
from memwing.workers.graph_write_worker import GraphWriteWorkerResult
from memwing.workers.runner import MemWingWorkerRunner, PipelineWorkerLane


def test_worker_runner_run_once_combines_outbox_and_graph_results() -> None:
    async def run() -> None:
        runner = MemWingWorkerRunner(
            derived_outbox_worker=_FakeDerivedOutboxWorker(claimed=2),
            graph_write_worker=_FakeGraphWriteWorker(claimed=1),
        )

        result = await runner.run_once(outbox_limit=5, graph_limit=7)

        assert result.claimed == 3
        assert result.outbox.claimed == 2
        assert result.graph.claimed == 1

    asyncio.run(run())


def test_worker_runner_page_memory_lane_filters_outbox_and_skips_graph() -> None:
    async def run() -> None:
        outbox_worker = _FakeDerivedOutboxWorker(claimed=2)
        graph_worker = _FakeGraphWriteWorker(claimed=1)
        runner = MemWingWorkerRunner(
            derived_outbox_worker=outbox_worker,
            graph_write_worker=graph_worker,
        )

        result = await runner.run_once(lane=PipelineWorkerLane.PAGE_MEMORY)

        assert result.claimed == 2
        assert outbox_worker.calls[-1]["job_types"] == ("page_memory.maybe_rebuild",)
        assert graph_worker.calls == []

    asyncio.run(run())


def test_worker_runner_graph_lane_skips_outbox() -> None:
    async def run() -> None:
        outbox_worker = _FakeDerivedOutboxWorker(claimed=2)
        graph_worker = _FakeGraphWriteWorker(claimed=1)
        runner = MemWingWorkerRunner(
            derived_outbox_worker=outbox_worker,
            graph_write_worker=graph_worker,
        )

        result = await runner.run_once(lane=PipelineWorkerLane.GRAPH)

        assert result.claimed == 1
        assert outbox_worker.calls == []
        assert graph_worker.calls[-1]["limit"] is None

    asyncio.run(run())


def test_worker_runner_all_lane_run_forever_does_not_block_outbox_on_graph() -> None:
    async def run() -> None:
        outbox_worker = _CountingDerivedOutboxWorker()
        graph_worker = _BlockingGraphWriteWorker()
        runner = MemWingWorkerRunner(
            derived_outbox_worker=outbox_worker,
            graph_write_worker=graph_worker,
        )

        task = asyncio.create_task(
            runner.run_forever(
                interval_seconds=0,
                idle_interval_seconds=0,
                outbox_limit=1,
                graph_limit=1,
            )
        )
        try:
            await asyncio.wait_for(outbox_worker.second_call.wait(), timeout=0.5)
            assert graph_worker.started.is_set()
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(run())


def test_derived_outbox_global_run_coalesces_scope_triggers_by_aggregate() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        filter_port = _RecordingLongTermFilter()
        scope_events = (
            _source_event("source_001", thread_id="thread_001", raw_payload_hash="hash_001"),
            _source_event("source_002", thread_id="thread_001", raw_payload_hash="hash_002"),
        )
        async with store.transaction() as tx:
            for source_event in scope_events:
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
                filter_port,
                lifecycle_transition=LifecycleTransitionService(store),
            ),
            page_memory_worker=None,
            worker_id="derived_outbox",
        )

        result = await worker.run_global_once(limit=10)

        assert result.claimed == 2
        assert result.succeeded == 2
        assert len(filter_port.requests) == 1
        assert tuple(event.id for event in filter_port.requests[0].source_events) == (
            "source_001",
            "source_002",
        )

    asyncio.run(run())


def test_page_memory_job_retries_when_worker_is_not_configured() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        source_event = _source_event("source_001", thread_id="thread_001", raw_payload_hash="hash_001")
        async with store.transaction() as tx:
            source, _ = await tx.source_events.insert_if_absent(source_event)
            await tx.outbox_jobs.enqueue(
                outbox_job(
                    source_event=source,
                    job_type="page_memory.maybe_rebuild",
                    now=source.created_at,
                )
            )

        worker = DerivedOutboxWorker(
            store,
            evidence_index=None,
            long_term_filter=LongTermFilterService(
                store,
                _RecordingLongTermFilter(),
                lifecycle_transition=LifecycleTransitionService(store),
            ),
            page_memory_worker=None,
            worker_id="derived_outbox",
        )

        result = await worker.run_global_once(limit=10, job_types=("page_memory.maybe_rebuild",))

        assert result.claimed == 1
        assert result.succeeded == 0
        assert result.retried == 1
        assert store.outbox_jobs[0].status == "pending"
        assert store.outbox_jobs[0].last_error == "RuntimeError"

    asyncio.run(run())


def _source_event(source_event_id: str, *, thread_id: str, raw_payload_hash: str) -> SourceEvent:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id=thread_id,
        shared_group_id=None,
        author_id=None,
        author_name=None,
        source_type="agent_runtime.message_ingested",
        content=f"Content for {source_event_id}.",
        content_preview=f"Content for {source_event_id}.",
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
        runtime_event_idempotency_key=source_event_id,
    )


class _RecordingLongTermFilter:
    def __init__(self) -> None:
        self.requests: list[LongTermFilterRequest] = []

    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        self.requests.append(request)
        return ()


class _FakeDerivedOutboxWorker:
    def __init__(self, *, claimed: int) -> None:
        self._claimed = claimed
        self.calls: list[dict[str, object]] = []

    async def run_global_once(self, **kwargs):
        from memwing.workers.derived_outbox_worker import DerivedOutboxWorkerResult

        self.calls.append(kwargs)
        return DerivedOutboxWorkerResult(
            claimed=self._claimed,
            succeeded=self._claimed,
            retried=0,
            dead_lettered=0,
            evidence_indexed_source_events=0,
        )


class _FakeGraphWriteWorker:
    def __init__(self, *, claimed: int) -> None:
        self._claimed = claimed
        self.calls: list[dict[str, object]] = []

    async def run_once(self, **kwargs) -> GraphWriteWorkerResult:
        self.calls.append(kwargs)
        return GraphWriteWorkerResult(
            claimed=self._claimed,
            succeeded=self._claimed,
            retried=0,
            dead_lettered=0,
        )


class _CountingDerivedOutboxWorker:
    def __init__(self) -> None:
        self.calls = 0
        self.second_call = asyncio.Event()

    async def run_global_once(self, **kwargs):
        from memwing.workers.derived_outbox_worker import DerivedOutboxWorkerResult

        self.calls += 1
        if self.calls >= 2:
            self.second_call.set()
        return DerivedOutboxWorkerResult(
            claimed=1,
            succeeded=1,
            retried=0,
            dead_lettered=0,
            evidence_indexed_source_events=0,
        )


class _BlockingGraphWriteWorker:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run_once(self, **kwargs) -> GraphWriteWorkerResult:
        self.started.set()
        await asyncio.sleep(60)
        return GraphWriteWorkerResult(
            claimed=1,
            succeeded=1,
            retried=0,
            dead_lettered=0,
        )
