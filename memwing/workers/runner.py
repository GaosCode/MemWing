from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from memwing.workers.derived_outbox_worker import (
    EVIDENCE_INDEX_JOB_TYPE,
    LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
    PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
    PUSH_CANDIDATE_TRIGGER_JOB_TYPE,
    PUSH_CANDIDATE_SEND_JOB_TYPE,
    WORKING_MEMORY_APPEND_JOB_TYPE,
    DerivedOutboxWorker,
    DerivedOutboxWorkerResult,
)
from memwing.workers.graph_write_worker import GraphWriteWorker, GraphWriteWorkerResult


class PipelineWorkerLane(StrEnum):
    ALL = "all"
    OUTBOX = "outbox"
    GRAPH = "graph"
    EVIDENCE = "evidence"
    WORKING_MEMORY = "working-memory"
    PAGE_MEMORY = "page-memory"
    LONG_TERM_FILTER = "long-term-filter"
    PUSH = "push"


@dataclass(frozen=True, slots=True)
class MemWingWorkerRunResult:
    outbox: DerivedOutboxWorkerResult
    graph: GraphWriteWorkerResult

    @property
    def claimed(self) -> int:
        return self.outbox.claimed + self.graph.claimed


class MemWingWorkerRunner:
    def __init__(
        self,
        *,
        derived_outbox_worker: DerivedOutboxWorker,
        graph_write_worker: GraphWriteWorker | None,
    ) -> None:
        self._derived_outbox_worker = derived_outbox_worker
        self._graph_write_worker = graph_write_worker

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        outbox_limit: int = 20,
        graph_limit: int | None = None,
        lane: PipelineWorkerLane = PipelineWorkerLane.ALL,
    ) -> MemWingWorkerRunResult:
        run_at = now or datetime.now(UTC)
        outbox = await self._run_outbox_once(now=run_at, limit=outbox_limit, lane=lane)
        graph = await self._run_graph_once(now=run_at, limit=graph_limit, lane=lane)
        return MemWingWorkerRunResult(outbox=outbox, graph=graph)

    async def run_forever(
        self,
        *,
        interval_seconds: float,
        idle_interval_seconds: float | None = None,
        outbox_limit: int = 20,
        graph_limit: int | None = None,
        lane: PipelineWorkerLane = PipelineWorkerLane.ALL,
    ) -> None:
        idle_interval = interval_seconds if idle_interval_seconds is None else idle_interval_seconds
        if lane == PipelineWorkerLane.ALL:
            await asyncio.gather(
                self._run_outbox_lane_forever(
                    lane=PipelineWorkerLane.EVIDENCE,
                    interval_seconds=interval_seconds,
                    idle_interval_seconds=idle_interval,
                    outbox_limit=outbox_limit,
                ),
                self._run_outbox_lane_forever(
                    lane=PipelineWorkerLane.WORKING_MEMORY,
                    interval_seconds=interval_seconds,
                    idle_interval_seconds=idle_interval,
                    outbox_limit=outbox_limit,
                ),
                self._run_outbox_lane_forever(
                    lane=PipelineWorkerLane.PAGE_MEMORY,
                    interval_seconds=interval_seconds,
                    idle_interval_seconds=idle_interval,
                    outbox_limit=outbox_limit,
                ),
                self._run_outbox_lane_forever(
                    lane=PipelineWorkerLane.LONG_TERM_FILTER,
                    interval_seconds=interval_seconds,
                    idle_interval_seconds=idle_interval,
                    outbox_limit=outbox_limit,
                ),
                self._run_outbox_lane_forever(
                    lane=PipelineWorkerLane.PUSH,
                    interval_seconds=interval_seconds,
                    idle_interval_seconds=idle_interval,
                    outbox_limit=outbox_limit,
                ),
                self._run_graph_forever(
                    interval_seconds=interval_seconds,
                    idle_interval_seconds=idle_interval,
                    graph_limit=graph_limit,
                ),
            )
            return
        while True:
            result = await self.run_once(
                outbox_limit=outbox_limit,
                graph_limit=graph_limit,
                lane=lane,
            )
            if result.claimed == 0:
                await asyncio.sleep(idle_interval)
            else:
                await asyncio.sleep(interval_seconds)

    async def _run_outbox_lane_forever(
        self,
        *,
        lane: PipelineWorkerLane,
        interval_seconds: float,
        idle_interval_seconds: float,
        outbox_limit: int,
    ) -> None:
        while True:
            outbox = await self._run_outbox_once(
                now=datetime.now(UTC),
                limit=outbox_limit,
                lane=lane,
            )
            await asyncio.sleep(interval_seconds if outbox.claimed else idle_interval_seconds)

    async def _run_graph_forever(
        self,
        *,
        interval_seconds: float,
        idle_interval_seconds: float,
        graph_limit: int | None,
    ) -> None:
        while True:
            graph = await self._run_graph_once(
                now=datetime.now(UTC),
                limit=graph_limit,
                lane=PipelineWorkerLane.GRAPH,
            )
            await asyncio.sleep(interval_seconds if graph.claimed else idle_interval_seconds)

    async def _run_outbox_once(
        self,
        *,
        now: datetime,
        limit: int | None,
        lane: PipelineWorkerLane,
    ) -> DerivedOutboxWorkerResult:
        job_types = _outbox_job_types_for_lane(lane)
        if job_types == ():
            return DerivedOutboxWorkerResult(
                claimed=0,
                succeeded=0,
                retried=0,
                dead_lettered=0,
                evidence_indexed_source_events=0,
            )
        return await self._derived_outbox_worker.run_global_once(
            now=now,
            limit=limit,
            job_types=job_types,
        )

    async def _run_graph_once(
        self,
        *,
        now: datetime,
        limit: int,
        lane: PipelineWorkerLane,
    ) -> GraphWriteWorkerResult:
        if lane not in (PipelineWorkerLane.ALL, PipelineWorkerLane.GRAPH):
            return GraphWriteWorkerResult(claimed=0, succeeded=0, retried=0, dead_lettered=0)
        if self._graph_write_worker is None:
            return GraphWriteWorkerResult(claimed=0, succeeded=0, retried=0, dead_lettered=0)
        return await self._graph_write_worker.run_once(now=now, limit=limit)


def _outbox_job_types_for_lane(lane: PipelineWorkerLane) -> tuple[str, ...] | None:
    if lane in (PipelineWorkerLane.ALL, PipelineWorkerLane.OUTBOX):
        return None
    if lane == PipelineWorkerLane.GRAPH:
        return ()
    if lane == PipelineWorkerLane.EVIDENCE:
        return (EVIDENCE_INDEX_JOB_TYPE,)
    if lane == PipelineWorkerLane.WORKING_MEMORY:
        return (WORKING_MEMORY_APPEND_JOB_TYPE,)
    if lane == PipelineWorkerLane.PAGE_MEMORY:
        return (PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,)
    if lane == PipelineWorkerLane.LONG_TERM_FILTER:
        return (LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,)
    if lane == PipelineWorkerLane.PUSH:
        return (PUSH_CANDIDATE_TRIGGER_JOB_TYPE, PUSH_CANDIDATE_SEND_JOB_TYPE)
    raise ValueError(f"unsupported pipeline lane: {lane}")
