from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from memwing.application.failure_semantics import classify_failure
from memwing.core.errors import MemWingFailure
from memwing.core.models import AuditEvent, OutboxJob
from memwing.ports.event_store import EventStoreUnitOfWorkPort


OutboxJobHandler = Callable[[OutboxJob], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class OutboxWorkerResult:
    claimed: int
    succeeded: int
    retried: int
    dead_lettered: int


class OutboxWorker:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        worker_id: str,
        handlers: dict[str, OutboxJobHandler],
        lock_duration: timedelta = timedelta(minutes=5),
        retry_delay: timedelta = timedelta(minutes=1),
    ) -> None:
        self._unit_of_work = unit_of_work
        self._worker_id = worker_id
        self._handlers = handlers
        self._lock_duration = lock_duration
        self._retry_delay = retry_delay

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        limit: int = 1,
        project_memory_space_id: str | None = None,
        job_type: str | None = None,
        job_types: tuple[str, ...] | None = None,
        aggregate_key: str | None = None,
    ) -> OutboxWorkerResult:
        if job_type is not None and job_types is not None:
            raise ValueError("job_type and job_types filters are mutually exclusive")
        if aggregate_key is not None and job_type is None:
            raise ValueError("aggregate_key filtering requires job_type")
        if aggregate_key is not None and project_memory_space_id is None:
            raise ValueError("aggregate_key filtering requires project_memory_space_id")

        run_at = now or datetime.now(UTC)
        async with self._unit_of_work.transaction() as tx:
            if (
                project_memory_space_id is not None
                and job_type is not None
                and aggregate_key is not None
            ):
                claimed = await tx.outbox_jobs.claim_pending_for_project_type_and_aggregate(
                    project_memory_space_id=project_memory_space_id,
                    job_type=job_type,
                    aggregate_key=aggregate_key,
                    now=run_at,
                    worker_id=self._worker_id,
                    lock_duration=self._lock_duration,
                    limit=limit,
                )
            elif project_memory_space_id is not None and job_type is not None:
                claimed = await tx.outbox_jobs.claim_pending_for_project_and_type(
                    project_memory_space_id=project_memory_space_id,
                    job_type=job_type,
                    now=run_at,
                    worker_id=self._worker_id,
                    lock_duration=self._lock_duration,
                    limit=limit,
                )
            elif project_memory_space_id is None and job_type is not None:
                claimed = await tx.outbox_jobs.claim_pending_for_types(
                    job_types=(job_type,),
                    now=run_at,
                    worker_id=self._worker_id,
                    lock_duration=self._lock_duration,
                    limit=limit,
                )
            elif project_memory_space_id is None and job_types is not None:
                claimed = await tx.outbox_jobs.claim_pending_for_types(
                    job_types=job_types,
                    now=run_at,
                    worker_id=self._worker_id,
                    lock_duration=self._lock_duration,
                    limit=limit,
                )
            elif project_memory_space_id is None:
                claimed = await tx.outbox_jobs.claim_pending(
                    now=run_at,
                    worker_id=self._worker_id,
                    lock_duration=self._lock_duration,
                    limit=limit,
                )
            else:
                claimed = await tx.outbox_jobs.claim_pending_for_project(
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
            handler = self._handlers.get(job.job_type)
            try:
                if handler is None:
                    raise RuntimeError(f"no handler registered for outbox job type {job.job_type}")
                await handler(job)
            except Exception as exc:
                failure = classify_failure(exc, audit_stage="outbox.handler")
                updated = await self._record_failure(
                    job=job,
                    error=_safe_error_summary(exc),
                    reason_code=failure.reason_code,
                    now=run_at,
                )
                if updated.status == "dead_letter":
                    dead_lettered += 1
                else:
                    retried += 1
            else:
                await self._record_success(job=job, now=run_at)
                succeeded += 1

        return OutboxWorkerResult(
            claimed=len(claimed),
            succeeded=succeeded,
            retried=retried,
            dead_lettered=dead_lettered,
        )

    async def _record_success(self, *, job: OutboxJob, now: datetime) -> None:
        async with self._unit_of_work.transaction() as tx:
            updated = await tx.outbox_jobs.mark_succeeded(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
            )
            await tx.audit_events.record(
                _audit_event(
                    job=updated,
                    stage="outbox.succeeded",
                    decision="succeeded",
                    reason_text=None,
                    now=now,
                )
            )

    async def _record_failure(
        self,
        *,
        job: OutboxJob,
        error: str,
        reason_code: str,
        now: datetime,
    ) -> OutboxJob:
        async with self._unit_of_work.transaction() as tx:
            updated = await tx.outbox_jobs.mark_failed(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
                error=error,
                retry_delay=self._retry_delay,
            )
            stage = "outbox.dead_letter" if updated.status == "dead_letter" else "outbox.failed"
            decision = "dead_letter" if updated.status == "dead_letter" else "retry"
            await tx.audit_events.record(
                _audit_event(
                    job=updated,
                    stage=stage,
                    decision=decision,
                    reason_code=reason_code,
                    reason_text=error,
                    now=now,
                )
            )
            return updated

    async def record_success(self, *, job: OutboxJob, now: datetime) -> None:
        await self._record_success(job=job, now=now)

    async def record_handler_failure(self, *, job: OutboxJob, exc: Exception, now: datetime) -> OutboxJob:
        failure = classify_failure(exc, audit_stage="outbox.handler")
        return await self._record_failure(
            job=job,
            error=_safe_error_summary(exc),
            reason_code=failure.reason_code,
            now=now,
        )


def _audit_event(
    *,
    job: OutboxJob,
    stage: str,
    decision: str,
    reason_text: str | None,
    now: datetime,
    reason_code: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid4()),
        trace_id=f"outbox:{job.id}",
        entity_type="outbox_job",
        entity_id=job.id,
        stage=stage,
        input_ref=job.id,
        output_ref=job.status,
        decision=decision,
        reason_code=reason_code,
        reason_text=reason_text,
        source_event_ids=(job.source_event_id,),
        latency_ms=None,
        created_at=now,
    )


def _safe_error_summary(exc: Exception) -> str:
    if isinstance(exc, MemWingFailure):
        return _clip_error_summary(f"{exc.reason_code}: {exc.safe_message}")
    return exc.__class__.__name__


def _clip_error_summary(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."
