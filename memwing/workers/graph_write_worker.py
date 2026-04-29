from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from memwing.core.models import (
    AuditEvent,
    GraphWriteJob,
    GraphWriteResult,
    MemoryGraphLink,
    MemoryGraphLinkType,
)
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort, GraphWriteRequest


@dataclass(frozen=True, slots=True)
class GraphWriteWorkerResult:
    claimed: int
    succeeded: int
    retried: int
    dead_lettered: int


class GraphWriteWorker:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        graph_backend: GraphBackendPort,
        worker_id: str,
        lock_duration: timedelta = timedelta(minutes=5),
        retry_delay: timedelta = timedelta(minutes=1),
    ) -> None:
        self._unit_of_work = unit_of_work
        self._graph_backend = graph_backend
        self._worker_id = worker_id
        self._lock_duration = lock_duration
        self._retry_delay = retry_delay

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        limit: int = 1,
    ) -> GraphWriteWorkerResult:
        run_at = now or datetime.now(UTC)
        async with self._unit_of_work.transaction() as tx:
            claimed = await tx.graph_write_jobs.claim_pending(
                now=run_at,
                worker_id=self._worker_id,
                lock_duration=self._lock_duration,
                limit=limit,
            )

        succeeded = 0
        retried = 0
        dead_lettered = 0
        for job in claimed:
            try:
                request = await self._build_request(job)
                graph_result = await self._graph_backend.ingest_graph_job(request)
                await self._record_success(job=job, graph_result=graph_result, now=run_at)
            except Exception as exc:
                updated = await self._record_failure(job=job, error=str(exc), now=run_at)
                if updated.status == "dead_letter":
                    dead_lettered += 1
                else:
                    retried += 1
            else:
                succeeded += 1

        return GraphWriteWorkerResult(
            claimed=len(claimed),
            succeeded=succeeded,
            retried=retried,
            dead_lettered=dead_lettered,
        )

    async def _build_request(self, job: GraphWriteJob) -> GraphWriteRequest:
        async with self._unit_of_work.transaction() as tx:
            memory_item = await tx.memory_items.get(job.memory_id)
            if memory_item is None:
                raise RuntimeError(f"missing memory item {job.memory_id}")

            source_events = []
            for source_event_id in job.source_event_ids:
                source_event = await tx.source_events.get_source_event(source_event_id)
                if source_event is None:
                    raise RuntimeError(f"missing source event {source_event_id}")
                source_events.append(source_event)

        return GraphWriteRequest(
            job=job,
            memory_item=memory_item,
            source_events=tuple(source_events),
        )

    async def _record_success(
        self,
        *,
        job: GraphWriteJob,
        graph_result: GraphWriteResult,
        now: datetime,
    ) -> int:
        async with self._unit_of_work.transaction() as tx:
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

            updated = await tx.graph_write_jobs.mark_succeeded(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
            )
            await tx.audit_events.record(
                _audit_event(
                    job=updated,
                    stage="graph_write.succeeded",
                    decision="succeeded",
                    output_ref=f"memory_graph_links:{link_count}",
                    reason_text=None,
                    now=now,
                )
            )
            return link_count

    async def _record_failure(
        self,
        *,
        job: GraphWriteJob,
        error: str,
        now: datetime,
    ) -> GraphWriteJob:
        async with self._unit_of_work.transaction() as tx:
            updated = await tx.graph_write_jobs.mark_failed(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
                error=error,
                retry_delay=self._retry_delay,
            )
            is_dead_letter = updated.status == "dead_letter"
            await tx.audit_events.record(
                _audit_event(
                    job=updated,
                    stage="graph_write.dead_letter" if is_dead_letter else "graph_write.retry",
                    decision="dead_letter" if is_dead_letter else "retry",
                    output_ref=updated.status,
                    reason_text=error,
                    now=now,
                )
            )
            return updated


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


def _audit_event(
    *,
    job: GraphWriteJob,
    stage: str,
    decision: str,
    output_ref: str | None,
    reason_text: str | None,
    now: datetime,
) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid4()),
        trace_id=f"graph_write:{job.id}",
        entity_type="graph_write_job",
        entity_id=job.id,
        stage=stage,
        input_ref=job.id,
        output_ref=output_ref,
        decision=decision,
        reason_code=None,
        reason_text=reason_text,
        source_event_ids=job.source_event_ids,
        latency_ms=None,
        created_at=now,
    )
