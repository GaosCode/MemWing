from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from memwing.core.models import GraphWriteJob, MemoryGraphLink
from memwing.ports.event_store import OutboxLockOwnershipError

from .in_memory_transaction_view import InMemoryTransactionView


class InMemoryGraphWriteJobRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def enqueue(self, job: GraphWriteJob) -> GraphWriteJob:
        existing_id = self._tx.state.graph_job_by_idempotency_key.get(job.idempotency_key)
        if existing_id is not None:
            return self._tx.state.graph_write_jobs[existing_id]

        self._tx.state.graph_write_jobs[job.id] = job
        self._tx.state.graph_job_by_idempotency_key[job.idempotency_key] = job.id
        return job

    async def claim_pending(
        self,
        *,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[GraphWriteJob, ...]:
        eligible = [
            job
            for job in self._tx.state.graph_write_jobs.values()
            if _is_graph_job_claimable(job, now)
        ]
        eligible.sort(
            key=lambda job: (
                0 if job.status == "pending" else 1,
                job.next_run_at,
                -job.priority,
                job.created_at,
            )
        )

        claimed: list[GraphWriteJob] = []
        for job in eligible[:limit]:
            updated = replace(
                job,
                status="processing",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + lock_duration,
                updated_at=now,
            )
            self._tx.state.graph_write_jobs[job.id] = updated
            claimed.append(updated)
        return tuple(claimed)

    async def mark_succeeded(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
    ) -> GraphWriteJob:
        job = self._get_locked_job(job_id, locked_by)
        updated = replace(
            job,
            status="succeeded",
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            last_error=None,
            updated_at=now,
        )
        self._tx.state.graph_write_jobs[job_id] = updated
        return updated

    async def mark_failed(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
        retry_delay: timedelta,
    ) -> GraphWriteJob:
        job = self._get_locked_job(job_id, locked_by)
        attempts = job.attempts + 1
        if attempts >= job.max_attempts:
            updated = replace(
                job,
                status="dead_letter",
                attempts=attempts,
                locked_at=None,
                locked_by=None,
                lock_expires_at=None,
                last_error=error,
                dead_letter_reason=error,
                updated_at=now,
            )
        else:
            updated = replace(
                job,
                status="pending",
                attempts=attempts,
                next_run_at=now + retry_delay,
                locked_at=None,
                locked_by=None,
                lock_expires_at=None,
                last_error=error,
                updated_at=now,
            )
        self._tx.state.graph_write_jobs[job_id] = updated
        return updated

    def _get_locked_job(self, job_id: str, locked_by: str) -> GraphWriteJob:
        job = self._tx.state.graph_write_jobs[job_id]
        if job.status != "processing" or job.locked_by != locked_by:
            raise OutboxLockOwnershipError("graph write job is not locked by this worker")
        return job


class InMemoryMemoryGraphLinkRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert(self, link: MemoryGraphLink) -> MemoryGraphLink:
        key = (
            link.backend,
            link.backend_object_type,
            link.backend_object_id,
            link.memory_id,
            link.link_type,
        )
        existing_id = self._tx.state.memory_graph_link_by_backend_object.get(key)
        if existing_id is not None:
            return self._tx.state.memory_graph_links[existing_id]

        self._tx.state.memory_graph_links[link.id] = link
        self._tx.state.memory_graph_link_by_backend_object[key] = link.id
        return link

    async def list_by_memory(self, memory_id: str) -> tuple[MemoryGraphLink, ...]:
        return tuple(
            link
            for link in self._tx.state.memory_graph_links.values()
            if link.memory_id == memory_id
        )


def _is_graph_job_claimable(job: GraphWriteJob, now: datetime) -> bool:
    if job.status == "pending" and job.next_run_at <= now:
        return True
    return (
        job.status == "processing"
        and job.lock_expires_at is not None
        and job.lock_expires_at <= now
    )
