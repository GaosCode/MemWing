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

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
        sort: str | None = None,
    ) -> tuple[GraphWriteJob, ...]:
        jobs = [
            job
            for job in self._tx.state.graph_write_jobs.values()
            if job.project_memory_space_id == project_memory_space_id
        ]
        jobs.sort(key=lambda job: (_graph_job_sort_value(job, sort), job.id), reverse=True)
        return tuple(jobs[:limit])

    async def list_for_source_events(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
    ) -> tuple[GraphWriteJob, ...]:
        source_ids = set(source_event_ids)
        jobs = [
            job
            for job in self._tx.state.graph_write_jobs.values()
            if job.project_memory_space_id == project_memory_space_id
            and source_ids.intersection(job.source_event_ids)
        ]
        jobs.sort(key=lambda job: (job.created_at, job.id))
        return tuple(jobs)

    async def claim_pending(
        self,
        *,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
        max_project_concurrency: int = 1,
    ) -> tuple[GraphWriteJob, ...]:
        if limit <= 0:
            return ()

        active_project_counts = _active_project_serialization_key_counts(
            tuple(self._tx.state.graph_write_jobs.values()),
            now,
        )
        blocked_serialization_keys = {
            job.serialization_key
            for job in self._tx.state.graph_write_jobs.values()
            if _is_unexpired_processing_graph_job(job, now)
        }
        eligible = [
            job
            for job in self._tx.state.graph_write_jobs.values()
            if _is_graph_job_claimable(job, now)
            and job.serialization_key not in blocked_serialization_keys
        ]
        eligible = _eligible_graph_jobs_for_project_concurrency(
            eligible,
            active_project_counts=active_project_counts,
            max_project_concurrency=max_project_concurrency,
        )

        claimed: list[GraphWriteJob] = []
        claimed_serialization_keys_by_project: dict[str, set[str]] = {}
        for job in eligible:
            project_keys = claimed_serialization_keys_by_project.setdefault(
                job.project_memory_space_id,
                set(),
            )
            active_count = active_project_counts.get(job.project_memory_space_id, 0)
            if job.serialization_key not in project_keys:
                if active_count + len(project_keys) >= max_project_concurrency:
                    continue

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
            project_keys.add(job.serialization_key)
            if len(claimed) >= limit:
                break
        return tuple(claimed)

    async def claim_pending_for_project(
        self,
        *,
        project_memory_space_id: str,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
        max_project_concurrency: int = 1,
    ) -> tuple[GraphWriteJob, ...]:
        if limit <= 0:
            return ()

        project_jobs = tuple(
            job
            for job in self._tx.state.graph_write_jobs.values()
            if job.project_memory_space_id == project_memory_space_id
        )
        active_project_counts = _active_project_serialization_key_counts(project_jobs, now)
        blocked_serialization_keys = {
            job.serialization_key
            for job in project_jobs
            if _is_unexpired_processing_graph_job(job, now)
        }
        eligible = [
            job
            for job in project_jobs
            if _is_graph_job_claimable(job, now)
            and job.serialization_key not in blocked_serialization_keys
        ]
        eligible = _eligible_graph_jobs_for_project_concurrency(
            eligible,
            active_project_counts=active_project_counts,
            max_project_concurrency=max_project_concurrency,
        )

        claimed: list[GraphWriteJob] = []
        claimed_serialization_keys: set[str] = set()
        for job in eligible:
            active_count = active_project_counts.get(project_memory_space_id, 0)
            if job.serialization_key not in claimed_serialization_keys:
                if active_count + len(claimed_serialization_keys) >= max_project_concurrency:
                    continue

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
            claimed_serialization_keys.add(job.serialization_key)
            if len(claimed) >= limit:
                break
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

    async def extend_lock(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        lock_duration: timedelta,
    ) -> GraphWriteJob:
        job = self._get_locked_job(job_id, locked_by)
        updated = replace(
            job,
            locked_at=now,
            lock_expires_at=now + lock_duration,
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

    async def mark_dead_letter(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
    ) -> GraphWriteJob:
        job = self._get_locked_job(job_id, locked_by)
        updated = replace(
            job,
            status="dead_letter",
            attempts=job.attempts + 1,
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            last_error=error,
            dead_letter_reason=error,
            updated_at=now,
        )
        self._tx.state.graph_write_jobs[job_id] = updated
        return updated

    async def retry_dead_letter(
        self,
        *,
        job_id: str,
        project_memory_space_id: str,
        now: datetime,
    ) -> GraphWriteJob | None:
        job = self._tx.state.graph_write_jobs.get(job_id)
        if job is None or job.project_memory_space_id != project_memory_space_id:
            return None
        if job.status != "dead_letter":
            return None
        updated = replace(
            job,
            status="pending",
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            last_error=None,
            dead_letter_reason=None,
            next_run_at=now,
            updated_at=now,
        )
        self._tx.state.graph_write_jobs[job_id] = updated
        return updated

    def _get_locked_job(self, job_id: str, locked_by: str) -> GraphWriteJob:
        job = self._tx.state.graph_write_jobs[job_id]
        if job.status != "processing" or job.locked_by != locked_by:
            raise OutboxLockOwnershipError("graph write job is not locked by this worker")
        return job


def _graph_job_sort_value(job: GraphWriteJob, sort: str | None) -> object:
    if sort == "created_at":
        return job.created_at
    if sort == "next_run_at":
        return job.next_run_at
    if sort == "priority":
        return job.priority
    return job.updated_at


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

    async def list_by_backend_objects(
        self,
        *,
        project_memory_space_id: str,
        backend: str,
        backend_object_type: str,
        backend_object_ids: tuple[str, ...],
    ) -> tuple[MemoryGraphLink, ...]:
        object_ids = set(backend_object_ids)
        if not object_ids:
            return ()
        return tuple(
            link
            for link in self._tx.state.memory_graph_links.values()
            if link.project_memory_space_id == project_memory_space_id
            and link.backend == backend
            and link.backend_object_type == backend_object_type
            and link.backend_object_id in object_ids
        )


def _is_graph_job_claimable(job: GraphWriteJob, now: datetime) -> bool:
    if job.status == "pending" and job.next_run_at <= now:
        return True
    return (
        job.status == "processing"
        and job.lock_expires_at is not None
        and job.lock_expires_at <= now
    )


def _is_unexpired_processing_graph_job(job: GraphWriteJob, now: datetime) -> bool:
    return (
        job.status == "processing"
        and (job.lock_expires_at is None or job.lock_expires_at > now)
    )


def _active_project_serialization_key_counts(
    jobs: tuple[GraphWriteJob, ...],
    now: datetime,
) -> dict[str, int]:
    keys_by_project: dict[str, set[str]] = {}
    for job in jobs:
        if not _is_unexpired_processing_graph_job(job, now):
            continue
        keys_by_project.setdefault(job.project_memory_space_id, set()).add(job.serialization_key)
    return {project_id: len(keys) for project_id, keys in keys_by_project.items()}


def _eligible_graph_jobs_for_project_concurrency(
    jobs: list[GraphWriteJob],
    *,
    active_project_counts: dict[str, int],
    max_project_concurrency: int,
) -> list[GraphWriteJob]:
    if max_project_concurrency <= 0:
        return []

    jobs.sort(key=_graph_claim_sort_key)
    ordered_keys_by_project: dict[str, list[str]] = {}
    for job in jobs:
        keys = ordered_keys_by_project.setdefault(job.project_memory_space_id, [])
        if job.serialization_key not in keys:
            keys.append(job.serialization_key)

    allowed_keys: set[str] = set()
    for project_id, keys in ordered_keys_by_project.items():
        remaining = max_project_concurrency - active_project_counts.get(project_id, 0)
        if remaining > 0:
            allowed_keys.update(keys[:remaining])

    return [job for job in jobs if job.serialization_key in allowed_keys]


def _graph_claim_sort_key(job: GraphWriteJob) -> tuple[str, int, datetime, int, datetime, str]:
    return (
        job.serialization_key,
        0 if job.status == "processing" else 1,
        job.next_run_at,
        -job.priority,
        job.created_at,
        job.id,
    )
