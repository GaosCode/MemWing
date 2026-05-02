from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from memwing.application.failure_semantics import FailureClassification, classify_failure
from memwing.application.graph_write_processor import (
    GraphWriteProcessingResult,
    GraphWriteProcessor,
    GraphWriteProcessorInputError,
)
from memwing.core.models import AuditEvent, GraphWriteJob
from memwing.ports.event_store import EventStoreUnitOfWorkPort, OutboxLockOwnershipError
from memwing.ports.graph_backend import GraphBackendPort
from memwing.ports.lifecycle_transition import LifecycleTransitionPort


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
        lifecycle_transition: LifecycleTransitionPort | None = None,
        worker_id: str,
        lock_duration: timedelta = timedelta(minutes=5),
        retry_delay: timedelta = timedelta(minutes=1),
        backend_timeout: timedelta = timedelta(seconds=30),
    ) -> None:
        self._unit_of_work = unit_of_work
        self._worker_id = worker_id
        self._lock_duration = lock_duration
        self._retry_delay = retry_delay
        self._processor = GraphWriteProcessor(
            unit_of_work,
            graph_backend=graph_backend,
            lifecycle_transition=lifecycle_transition,
            worker_id=worker_id,
            lock_duration=lock_duration,
            backend_timeout=backend_timeout,
        )

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        limit: int = 1,
        project_memory_space_id: str | None = None,
    ) -> GraphWriteWorkerResult:
        run_at = now or datetime.now(UTC)
        async with self._unit_of_work.transaction() as tx:
            if project_memory_space_id is None:
                claimed = await tx.graph_write_jobs.claim_pending(
                    now=run_at,
                    worker_id=self._worker_id,
                    lock_duration=self._lock_duration,
                    limit=limit,
                )
            else:
                claimed = await tx.graph_write_jobs.claim_pending_for_project(
                    project_memory_space_id=project_memory_space_id,
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
                completion_at = now or datetime.now(UTC)
                processing_result = await self._processor.process(job, now=completion_at)
                await self._record_success(
                    job=job,
                    processing_result=processing_result,
                    now=completion_at,
                )
            except OutboxLockOwnershipError as exc:
                completion_at = now or datetime.now(UTC)
                await self._record_lock_ownership_failure(job=job, exc=exc, now=completion_at)
                raise
            except Exception as exc:
                completion_at = now or datetime.now(UTC)
                failure = classify_failure(exc, audit_stage="graph_write.failed")
                updated = await self._record_failure(
                    job=job,
                    error=_safe_error_summary(exc),
                    failure=failure,
                    now=completion_at,
                )
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

    async def _record_success(
        self,
        *,
        job: GraphWriteJob,
        processing_result: GraphWriteProcessingResult,
        now: datetime,
    ) -> int:
        async with self._unit_of_work.transaction() as tx:
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
                    output_ref=f"memory_graph_links:{processing_result.link_count}",
                    reason_text=None,
                    now=now,
                )
            )
            return processing_result.link_count

    async def _record_failure(
        self,
        *,
        job: GraphWriteJob,
        error: str,
        failure: FailureClassification,
        now: datetime,
    ) -> GraphWriteJob:
        async with self._unit_of_work.transaction() as tx:
            if failure.dead_letter and not failure.retryable:
                updated = await tx.graph_write_jobs.mark_dead_letter(
                    job_id=job.id,
                    locked_by=self._worker_id,
                    now=now,
                    error=error,
                )
            else:
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
                    reason_code=failure.reason_code,
                    reason_text=error,
                    now=now,
                )
            )
            return updated

    async def _record_lock_ownership_failure(
        self,
        *,
        job: GraphWriteJob,
        exc: OutboxLockOwnershipError,
        now: datetime,
    ) -> None:
        failure = classify_failure(exc, audit_stage="graph_write.lock_lost")
        async with self._unit_of_work.transaction() as tx:
            await tx.audit_events.record(
                _audit_event(
                    job=job,
                    stage="graph_write.lock_lost",
                    decision="aborted",
                    output_ref="lock_lost",
                    reason_code=failure.reason_code,
                    reason_text=_safe_error_summary(exc),
                    now=now,
                )
            )


def _safe_error_summary(exc: Exception) -> str:
    if isinstance(exc, GraphWriteProcessorInputError):
        return str(exc)
    return exc.__class__.__name__


def _audit_event(
    *,
    job: GraphWriteJob,
    stage: str,
    decision: str,
    output_ref: str | None,
    reason_text: str | None,
    now: datetime,
    reason_code: str | None = None,
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
        reason_code=reason_code,
        reason_text=reason_text,
        source_event_ids=job.source_event_ids,
        latency_ms=None,
        created_at=now,
    )
