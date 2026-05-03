from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from memwing.application.long_term_filter_service import (
    LongTermFilterProcessCommand,
    LongTermFilterService,
)
from memwing.core.models import OutboxJob, SourceEvent, WorkingMemoryEntry
from memwing.core.scope import EffectiveScope
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.workers.graph_write_worker import GraphWriteWorker, GraphWriteWorkerResult
from memwing.workers.outbox_worker import OutboxWorker, OutboxWorkerResult
from memwing.workers.page_memory_worker import PageMemoryWorker


@dataclass(frozen=True, slots=True)
class BenchmarkDrainResult:
    outbox_claimed: int
    outbox_succeeded: int
    outbox_retried: int
    outbox_dead_lettered: int
    graph_claimed: int
    graph_succeeded: int
    graph_retried: int
    graph_dead_lettered: int
    evidence_indexed_source_events: int
    pending_outbox_jobs: int
    pending_graph_write_jobs: int
    iterations: int
    drained: bool


class BenchmarkDrainWorker:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        evidence_index: EvidenceIndexPort | None,
        long_term_filter: LongTermFilterService,
        page_memory_worker: PageMemoryWorker | None,
        graph_write_worker: GraphWriteWorker | None,
        worker_id: str = "benchmark_drain",
    ) -> None:
        self._unit_of_work = unit_of_work
        self._evidence_index = evidence_index
        self._long_term_filter = long_term_filter
        self._page_memory_worker = page_memory_worker
        self._graph_write_worker = graph_write_worker
        self._worker_id = worker_id

    async def drain_scope(
        self,
        *,
        scope: EffectiveScope,
        max_iterations: int = 20,
        batch_size: int = 10,
    ) -> BenchmarkDrainResult:
        evidence_indexed_source_events = 0

        async def index_source_event(job: OutboxJob) -> None:
            nonlocal evidence_indexed_source_events
            await self._index_source_event(job)
            evidence_indexed_source_events += 1

        outbox_worker = OutboxWorker(
            self._unit_of_work,
            worker_id=self._worker_id,
            handlers={
                "evidence.index_source_event": index_source_event,
                "working_memory.append": self._append_working_memory,
                "page_memory.maybe_rebuild": self._maybe_rebuild_page_memory,
                "long_term_filter.classify": lambda job: self._classify_long_term(job, scope),
            },
            retry_delay=timedelta(0),
        )

        totals = _DrainTotals()
        drained = False
        for iteration in range(1, max_iterations + 1):
            outbox = await outbox_worker.run_once(
                project_memory_space_id=scope.project_memory_space_id,
                limit=batch_size,
            )
            totals.add_outbox(outbox)

            graph = await self._run_graph_batch(
                project_memory_space_id=scope.project_memory_space_id,
                limit=batch_size,
            )
            totals.add_graph(graph)

            if outbox.claimed == 0 and graph.claimed == 0:
                drained = True
                totals.iterations = iteration
                break
        else:
            totals.iterations = max_iterations

        pending = await self._pending_counts(scope.project_memory_space_id)
        return totals.result(
            drained=drained,
            evidence_indexed_source_events=evidence_indexed_source_events,
            pending_outbox_jobs=pending["outbox_jobs"],
            pending_graph_write_jobs=pending["graph_write_jobs"],
        )

    async def _index_source_event(self, job: OutboxJob) -> None:
        if self._evidence_index is None:
            raise RuntimeError("evidence index backend is not configured")
        source_event = await self._load_source_event(job.source_event_id)
        await self._evidence_index.index_source_event(
            source_event,
            _scope_from_source_event(source_event),
        )

    async def _append_working_memory(self, job: OutboxJob) -> None:
        source_event = await self._load_source_event(job.source_event_id)
        async with self._unit_of_work.transaction() as tx:
            sequence = await tx.working_memory_entries.next_sequence(
                project_memory_space_id=source_event.project_memory_space_id,
                thread_id=source_event.thread_id,
            )
            await tx.working_memory_entries.append(
                WorkingMemoryEntry(
                    id=_uuid("working_memory", source_event.id),
                    source_event_id=source_event.id,
                    project_memory_space_id=source_event.project_memory_space_id,
                    group_id=source_event.group_id,
                    thread_id=source_event.thread_id,
                    shared_group_id=source_event.shared_group_id,
                    content=source_event.content,
                    token_count=max(1, len(source_event.content.split())),
                    sequence=sequence,
                    flushed_at=None,
                    created_at=datetime.now(UTC),
                )
            )

    async def _maybe_rebuild_page_memory(self, job: OutboxJob) -> None:
        if self._page_memory_worker is None:
            return
        await self._page_memory_worker.maybe_rebuild(job)

    async def _classify_long_term(self, job: OutboxJob, scope: EffectiveScope) -> None:
        await self._long_term_filter.process_scope(
            LongTermFilterProcessCommand(
                scope=scope,
                now=datetime.now(UTC),
                trace_id=f"benchmark_long_term_filter:{job.id}",
            )
        )

    async def _run_graph_batch(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> GraphWriteWorkerResult:
        if self._graph_write_worker is None:
            return GraphWriteWorkerResult(claimed=0, succeeded=0, retried=0, dead_lettered=0)
        return await self._graph_write_worker.run_once(
            project_memory_space_id=project_memory_space_id,
            limit=limit,
        )

    async def _load_source_event(self, source_event_id: str) -> SourceEvent:
        async with self._unit_of_work.transaction() as tx:
            source_event = await tx.source_events.get_source_event(source_event_id)
        if source_event is None:
            raise RuntimeError("source event for outbox job was not found")
        return source_event

    async def _pending_counts(self, project_memory_space_id: str) -> dict[str, int]:
        async with self._unit_of_work.transaction() as tx:
            outbox_jobs = await tx.outbox_jobs.list_for_project(
                project_memory_space_id=project_memory_space_id,
                limit=10000,
            )
            graph_jobs = await tx.graph_write_jobs.list_for_project(
                project_memory_space_id=project_memory_space_id,
                limit=10000,
            )
        return {
            "outbox_jobs": sum(1 for job in outbox_jobs if job.status in ("pending", "processing")),
            "graph_write_jobs": sum(
                1 for job in graph_jobs if job.status in ("pending", "processing")
            ),
        }


@dataclass(slots=True)
class _DrainTotals:
    outbox_claimed: int = 0
    outbox_succeeded: int = 0
    outbox_retried: int = 0
    outbox_dead_lettered: int = 0
    graph_claimed: int = 0
    graph_succeeded: int = 0
    graph_retried: int = 0
    graph_dead_lettered: int = 0
    iterations: int = 0

    def add_outbox(self, result: OutboxWorkerResult) -> None:
        self.outbox_claimed += result.claimed
        self.outbox_succeeded += result.succeeded
        self.outbox_retried += result.retried
        self.outbox_dead_lettered += result.dead_lettered

    def add_graph(self, result: GraphWriteWorkerResult) -> None:
        self.graph_claimed += result.claimed
        self.graph_succeeded += result.succeeded
        self.graph_retried += result.retried
        self.graph_dead_lettered += result.dead_lettered

    def result(
        self,
        *,
        drained: bool,
        evidence_indexed_source_events: int,
        pending_outbox_jobs: int,
        pending_graph_write_jobs: int,
    ) -> BenchmarkDrainResult:
        return BenchmarkDrainResult(
            outbox_claimed=self.outbox_claimed,
            outbox_succeeded=self.outbox_succeeded,
            outbox_retried=self.outbox_retried,
            outbox_dead_lettered=self.outbox_dead_lettered,
            graph_claimed=self.graph_claimed,
            graph_succeeded=self.graph_succeeded,
            graph_retried=self.graph_retried,
            graph_dead_lettered=self.graph_dead_lettered,
            evidence_indexed_source_events=evidence_indexed_source_events,
            pending_outbox_jobs=pending_outbox_jobs,
            pending_graph_write_jobs=pending_graph_write_jobs,
            iterations=self.iterations,
            drained=drained,
        )


def _scope_from_source_event(source_event: SourceEvent) -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id=source_event.project_memory_space_id,
        group_ids=(source_event.group_id,) if source_event.group_id is not None else None,
        thread_id=source_event.thread_id,
        shared_group_id=source_event.shared_group_id,
        safe_mode_enabled=source_event.group_id is not None,
        cross_group_allowed=source_event.group_id is None,
    )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
