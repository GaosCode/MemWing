from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import uuid

from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import (
    GraphFact,
    GraphWriteJob,
    GraphWriteResult,
    MemoryGraphLink,
    MemoryGraphLinkType,
)
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort, GraphWriteRequest
from memwing.ports.lifecycle_transition import LifecycleTransitionPort, LifecycleTransitionRequest


@dataclass(frozen=True, slots=True)
class GraphWriteProcessingResult:
    link_count: int
    invalidated_memory_ids: tuple[str, ...]


class GraphWriteProcessor:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        graph_backend: GraphBackendPort,
        lifecycle_transition: LifecycleTransitionPort | None,
        worker_id: str,
        lock_duration: timedelta,
        backend_timeout: timedelta,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._graph_backend = graph_backend
        self._lifecycle_transition = lifecycle_transition
        self._worker_id = worker_id
        self._lock_duration = lock_duration
        self._backend_timeout = backend_timeout

    async def process(
        self,
        job: GraphWriteJob,
        *,
        now: datetime,
    ) -> GraphWriteProcessingResult:
        request = await self._build_request(job)
        graph_result = await asyncio.wait_for(
            self._graph_backend.ingest_graph_job(request),
            timeout=self._backend_timeout.total_seconds(),
        )
        self._ensure_lifecycle_port_for_invalidated_facts(graph_result.invalidated_facts)
        invalidated_memory_ids = await self._memory_ids_for_invalidated_facts(
            facts=graph_result.invalidated_facts,
            project_memory_space_id=job.project_memory_space_id,
        )
        await self._mark_invalidated_memories_needs_review(
            job=job,
            memory_ids=invalidated_memory_ids,
            now=now,
        )
        link_count = await self._write_graph_links_under_current_lock(
            job=job,
            graph_result=graph_result,
            now=now,
        )
        return GraphWriteProcessingResult(
            link_count=link_count,
            invalidated_memory_ids=invalidated_memory_ids,
        )

    async def _build_request(self, job: GraphWriteJob) -> GraphWriteRequest:
        async with self._unit_of_work.transaction() as tx:
            memory_item = await tx.memory_items.get(job.memory_id)
            if memory_item is None:
                raise GraphWriteProcessorInputError(f"missing memory item {job.memory_id}")

            source_events = []
            for source_event_id in job.source_event_ids:
                source_event = await tx.source_events.get_source_event(source_event_id)
                if source_event is None:
                    raise GraphWriteProcessorInputError(f"missing source event {source_event_id}")
                source_events.append(source_event)

        return GraphWriteRequest(
            job=job,
            memory_item=memory_item,
            source_events=tuple(source_events),
        )

    async def _write_graph_links_under_current_lock(
        self,
        *,
        job: GraphWriteJob,
        graph_result: GraphWriteResult,
        now: datetime,
    ) -> int:
        async with self._unit_of_work.transaction() as tx:
            await tx.graph_write_jobs.extend_lock(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
                lock_duration=self._lock_duration,
            )
            link_count = 0
            for episode_ref in graph_result.backend_episode_refs:
                await tx.memory_graph_links.upsert(
                    _memory_graph_link(
                        job=job,
                        source_event_id=job.source_event_ids[0],
                        backend=graph_result.backend,
                        backend_object_type="episode",
                        backend_object_id=episode_ref,
                        link_type="episode",
                        now=now,
                    )
                )
                link_count += 1

            for fact in graph_result.facts:
                if not fact.source_event_ids:
                    raise GraphWriteProcessorInputError("graph fact missing source event ids")
                source_event_id = fact.source_event_ids[0]
                await tx.memory_graph_links.upsert(
                    _memory_graph_link(
                        job=job,
                        source_event_id=source_event_id,
                        backend=graph_result.backend,
                        backend_object_type="fact",
                        backend_object_id=fact.fact_id,
                        link_type="fact",
                        now=now,
                    )
                )
                link_count += 1
            return link_count

    async def _extend_current_lock(
        self,
        *,
        job: GraphWriteJob,
        now: datetime,
    ) -> None:
        async with self._unit_of_work.transaction() as tx:
            await tx.graph_write_jobs.extend_lock(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
                lock_duration=self._lock_duration,
            )

    async def _memory_ids_for_invalidated_facts(
        self,
        *,
        facts: tuple[GraphFact, ...],
        project_memory_space_id: str,
    ) -> tuple[str, ...]:
        memory_ids: list[str] = []
        seen: set[str] = set()
        async with self._unit_of_work.transaction() as tx:
            for fact in facts:
                if not fact.source_event_ids:
                    raise GraphWriteProcessorInputError(
                        "invalidated graph fact missing source event ids"
                    )
                for source_event_id in fact.source_event_ids:
                    for item in await tx.memory_items.list_by_source_event(source_event_id):
                        if item.project_memory_space_id != project_memory_space_id:
                            continue
                        if item.id in seen:
                            continue
                        seen.add(item.id)
                        memory_ids.append(item.id)
        return tuple(memory_ids)

    def _ensure_lifecycle_port_for_invalidated_facts(
        self,
        facts: tuple[GraphFact, ...],
    ) -> None:
        if facts and self._lifecycle_transition is None:
            raise GraphWriteProcessorInputError(
                "lifecycle transition port required for graph invalidations"
            )

    async def _mark_invalidated_memories_needs_review(
        self,
        *,
        job: GraphWriteJob,
        memory_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        if not memory_ids:
            return
        if self._lifecycle_transition is None:
            raise GraphWriteProcessorInputError(
                "lifecycle transition port required for graph invalidations"
            )

        for memory_id in memory_ids:
            await self._extend_current_lock(job=job, now=now)
            await self._lifecycle_transition.transition(
                LifecycleTransitionRequest(
                    memory_id=memory_id,
                    action=LifecycleAction.MARK_NEEDS_REVIEW,
                    actor_id="graph_write_worker",
                    reason="graph fact invalidated",
                    idempotency_key=f"graph:{job.id}:invalidated:{memory_id}",
                    trace_id=f"graph_write:{job.id}",
                    now=now,
                )
            )


class GraphWriteProcessorInputError(RuntimeError):
    pass


def _memory_graph_link(
    *,
    job: GraphWriteJob,
    source_event_id: str,
    backend: str,
    backend_object_type: str,
    backend_object_id: str,
    link_type: MemoryGraphLinkType,
    now: datetime,
) -> MemoryGraphLink:
    return MemoryGraphLink(
        id=str(uuid.uuid4()),
        backend=backend,
        memory_id=job.memory_id,
        source_event_id=source_event_id,
        project_memory_space_id=job.project_memory_space_id,
        backend_space_id=job.project_memory_space_id,
        backend_object_type=backend_object_type,
        backend_object_id=backend_object_id,
        link_type=link_type,
        created_at=now,
    )
