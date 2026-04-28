from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

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
    ) -> OutboxWorkerResult:
        run_at = now or datetime.now(UTC)
        async with self._unit_of_work.transaction() as tx:
            claimed = await tx.outbox_jobs.claim_pending(
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
                updated = await self._record_failure(job=job, error=str(exc), now=run_at)
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

    async def _record_failure(self, *, job: OutboxJob, error: str, now: datetime) -> OutboxJob:
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
                    reason_text=error,
                    now=now,
                )
            )
            return updated


def _audit_event(
    *,
    job: OutboxJob,
    stage: str,
    decision: str,
    reason_text: str | None,
    now: datetime,
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
        reason_code=None,
        reason_text=reason_text,
        source_event_ids=(job.source_event_id,),
        latency_ms=None,
        created_at=now,
    )
