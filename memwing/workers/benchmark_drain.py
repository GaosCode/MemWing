from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from memwing.application.long_term_filter_service import LongTermFilterService
from memwing.core.scope import EffectiveScope
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.workers.derived_outbox_worker import (
    DerivedOutboxWorker,
    DerivedOutboxWorkerResult,
)
from memwing.workers.graph_write_worker import GraphWriteWorker, GraphWriteWorkerResult
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
        self._graph_write_worker = graph_write_worker
        self._derived_outbox_worker = DerivedOutboxWorker(
            unit_of_work,
            evidence_index=evidence_index,
            long_term_filter=long_term_filter,
            page_memory_worker=page_memory_worker,
            worker_id=worker_id,
            retry_delay=timedelta(0),
        )

    async def drain_scope(
        self,
        *,
        scope: EffectiveScope,
        max_iterations: int = 20,
        batch_size: int = 10,
        outbox_job_types: tuple[str, ...] | None = None,
    ) -> BenchmarkDrainResult:
        evidence_indexed_source_events = 0

        totals = _DrainTotals()
        drained = False
        for iteration in range(1, max_iterations + 1):
            outbox = await self._derived_outbox_worker.run_once(
                scope=scope,
                event_job_limit=batch_size,
                job_types=outbox_job_types,
            )
            totals.add_outbox(outbox)
            evidence_indexed_source_events += outbox.evidence_indexed_source_events

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

    def add_outbox(self, result: DerivedOutboxWorkerResult) -> None:
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
