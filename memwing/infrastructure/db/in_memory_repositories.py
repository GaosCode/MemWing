from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol

from memwing.core.models import AuditEvent, OutboxJob, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import OutboxLockOwnershipError

from .in_memory_scope import effective_scope_matches
from .in_memory_state import InMemoryState


class InMemoryTransactionView(Protocol):
    state: InMemoryState
    fail_on_outbox_job_type: str | None


class InMemorySourceEventRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def insert_if_absent(self, event: SourceEvent) -> tuple[SourceEvent, bool]:
        raw_key = (event.project_memory_space_id, event.raw_payload_hash)
        existing_id = self._tx.state.source_by_raw_hash.get(raw_key)
        if existing_id is not None:
            return self._tx.state.source_events[existing_id], False

        runtime_key = event.runtime_event_idempotency_key
        if runtime_key is not None:
            existing_id = self._tx.state.source_by_runtime_key.get(
                (event.project_memory_space_id, runtime_key)
            )
            if existing_id is not None:
                return self._tx.state.source_events[existing_id], False

        self._tx.state.source_events[event.id] = event
        self._tx.state.source_by_raw_hash[raw_key] = event.id
        if runtime_key is not None:
            self._tx.state.source_by_runtime_key[
                (event.project_memory_space_id, runtime_key)
            ] = event.id
        return event, True

    async def get_source_event(self, source_event_id: str) -> SourceEvent | None:
        return self._tx.state.source_events.get(source_event_id)

    async def redact_source_event(
        self,
        *,
        source_event_id: str,
        redacted_content: str,
        purged_at: datetime,
        purged_by: str,
        purge_reason: str,
        purge_level: str,
        graph_backend_raw_retained: bool,
    ) -> SourceEvent | None:
        event = self._tx.state.source_events.get(source_event_id)
        if event is None:
            return None
        updated = replace(
            event,
            content=redacted_content,
            content_preview=redacted_content,
            purged_at=purged_at,
            purged_by=purged_by,
            purge_reason=purge_reason,
            purge_level=purge_level,
            graph_backend_raw_retained=graph_backend_raw_retained,
        )
        self._tx.state.source_events[source_event_id] = updated
        return updated

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[SourceEvent, ...]:
        events = [
            event
            for event in self._tx.state.source_events.values()
            if event.project_memory_space_id == scope.project_memory_space_id
            and event.purged_at is None
            and event.purge_level == "none"
            and effective_scope_matches(
                group_id=event.group_id,
                thread_id=event.thread_id,
                shared_group_id=event.shared_group_id,
                scope=scope,
            )
        ]
        events.sort(key=lambda event: (event.event_time, event.id))
        return tuple(events[:limit])

    async def list_recent_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[SourceEvent, ...]:
        if limit <= 0:
            return ()
        events = [
            event
            for event in self._tx.state.source_events.values()
            if event.project_memory_space_id == scope.project_memory_space_id
            and event.purged_at is None
            and event.purge_level == "none"
            and effective_scope_matches(
                group_id=event.group_id,
                thread_id=event.thread_id,
                shared_group_id=event.shared_group_id,
                scope=scope,
            )
        ]
        events.sort(key=lambda event: (event.event_time, event.id), reverse=True)
        recent = events[:limit]
        recent.sort(key=lambda event: (event.event_time, event.id))
        return tuple(recent)


class InMemoryAuditEventRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def record(self, event: AuditEvent) -> AuditEvent:
        if event.idempotency_key is not None:
            existing = await self.get_by_idempotency_key(
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                idempotency_key=event.idempotency_key,
            )
            if existing is not None:
                return existing
        self._tx.state.audit_events[event.id] = event
        return event

    async def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
        limit: int,
    ) -> tuple[AuditEvent, ...]:
        events = [
            event
            for event in self._tx.state.audit_events.values()
            if event.entity_type == entity_type and event.entity_id == entity_id
        ]
        events.sort(key=lambda event: (event.created_at, event.id), reverse=True)
        return tuple(events[:limit])

    async def get_by_idempotency_key(
        self,
        *,
        entity_type: str,
        entity_id: str,
        idempotency_key: str,
    ) -> AuditEvent | None:
        for event in self._tx.state.audit_events.values():
            if (
                event.entity_type == entity_type
                and event.entity_id == entity_id
                and event.idempotency_key == idempotency_key
            ):
                return event
        return None


class InMemoryOutboxJobRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def enqueue(self, job: OutboxJob) -> OutboxJob:
        if self._tx.fail_on_outbox_job_type == job.job_type:
            raise RuntimeError(f"outbox enqueue failed for {job.job_type}")

        existing_id = self._tx.state.outbox_by_idempotency_key.get(job.idempotency_key)
        if existing_id is not None:
            return self._tx.state.outbox_jobs[existing_id]

        self._tx.state.outbox_jobs[job.id] = job
        self._tx.state.outbox_by_idempotency_key[job.idempotency_key] = job.id
        return job

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
        sort: str | None = None,
    ) -> tuple[OutboxJob, ...]:
        jobs = [
            job
            for job in self._tx.state.outbox_jobs.values()
            if job.project_memory_space_id == project_memory_space_id
        ]
        jobs.sort(
            key=lambda job: (_outbox_job_sort_value(job, sort), job.id),
            reverse=True,
        )
        return tuple(jobs[:limit])

    async def list_for_source_events(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
    ) -> tuple[OutboxJob, ...]:
        source_ids = set(source_event_ids)
        jobs = [
            job
            for job in self._tx.state.outbox_jobs.values()
            if job.project_memory_space_id == project_memory_space_id
            and job.source_event_id in source_ids
        ]
        jobs.sort(key=lambda job: (job.created_at, job.id))
        return tuple(jobs)

    async def list_for_project_type_and_aggregates(
        self,
        *,
        project_memory_space_id: str,
        job_type: str,
        aggregate_keys: tuple[str, ...],
    ) -> tuple[OutboxJob, ...]:
        aggregates = set(aggregate_keys)
        jobs = [
            job
            for job in self._tx.state.outbox_jobs.values()
            if job.project_memory_space_id == project_memory_space_id
            and job.job_type == job_type
            and job.aggregate_key in aggregates
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
    ) -> tuple[OutboxJob, ...]:
        eligible = [job for job in self._tx.state.outbox_jobs.values() if _is_claimable(job, now)]
        eligible.sort(
            key=lambda job: (
                0 if job.status == "pending" else 1,
                job.next_run_at,
                -job.priority,
                job.created_at,
            )
        )

        claimed: list[OutboxJob] = []
        for job in eligible[:limit]:
            updated = replace(
                job,
                status="processing",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + lock_duration,
                updated_at=now,
            )
            self._tx.state.outbox_jobs[job.id] = updated
            claimed.append(updated)
        return tuple(claimed)

    async def claim_pending_for_project(
        self,
        *,
        project_memory_space_id: str,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        eligible = [
            job
            for job in self._tx.state.outbox_jobs.values()
            if job.project_memory_space_id == project_memory_space_id and _is_claimable(job, now)
        ]
        eligible.sort(
            key=lambda job: (
                0 if job.status == "pending" else 1,
                job.next_run_at,
                -job.priority,
                job.created_at,
            )
        )

        claimed: list[OutboxJob] = []
        for job in eligible[:limit]:
            updated = replace(
                job,
                status="processing",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + lock_duration,
                updated_at=now,
            )
            self._tx.state.outbox_jobs[job.id] = updated
            claimed.append(updated)
        return tuple(claimed)

    async def claim_pending_for_types(
        self,
        *,
        job_types: tuple[str, ...],
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        selected = set(job_types)
        eligible = [
            job
            for job in self._tx.state.outbox_jobs.values()
            if job.job_type in selected and _is_claimable(job, now)
        ]
        eligible.sort(
            key=lambda job: (
                0 if job.status == "pending" else 1,
                job.next_run_at,
                -job.priority,
                job.created_at,
            )
        )

        claimed: list[OutboxJob] = []
        for job in eligible[:limit]:
            updated = replace(
                job,
                status="processing",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + lock_duration,
                updated_at=now,
            )
            self._tx.state.outbox_jobs[job.id] = updated
            claimed.append(updated)
        return tuple(claimed)

    async def claim_pending_for_project_and_type(
        self,
        *,
        project_memory_space_id: str,
        job_type: str,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        eligible = [
            job
            for job in self._tx.state.outbox_jobs.values()
            if job.project_memory_space_id == project_memory_space_id
            and job.job_type == job_type
            and _is_claimable(job, now)
        ]
        eligible.sort(
            key=lambda job: (
                0 if job.status == "pending" else 1,
                job.next_run_at,
                -job.priority,
                job.created_at,
            )
        )

        claimed: list[OutboxJob] = []
        for job in eligible[:limit]:
            updated = replace(
                job,
                status="processing",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + lock_duration,
                updated_at=now,
            )
            self._tx.state.outbox_jobs[job.id] = updated
            claimed.append(updated)
        return tuple(claimed)

    async def claim_pending_for_project_type_and_aggregate(
        self,
        *,
        project_memory_space_id: str,
        job_type: str,
        aggregate_key: str,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        eligible = [
            job
            for job in self._tx.state.outbox_jobs.values()
            if job.project_memory_space_id == project_memory_space_id
            and job.job_type == job_type
            and job.aggregate_key == aggregate_key
            and _is_claimable(job, now)
        ]
        eligible.sort(
            key=lambda job: (
                0 if job.status == "pending" else 1,
                job.next_run_at,
                -job.priority,
                job.created_at,
            )
        )

        claimed: list[OutboxJob] = []
        for job in eligible[:limit]:
            updated = replace(
                job,
                status="processing",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + lock_duration,
                updated_at=now,
            )
            self._tx.state.outbox_jobs[job.id] = updated
            claimed.append(updated)
        return tuple(claimed)

    async def mark_succeeded(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
    ) -> OutboxJob:
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
        self._tx.state.outbox_jobs[job_id] = updated
        return updated

    async def mark_failed(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
        retry_delay: timedelta,
    ) -> OutboxJob:
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
        self._tx.state.outbox_jobs[job_id] = updated
        return updated

    async def retry_dead_letter(
        self,
        *,
        job_id: str,
        project_memory_space_id: str,
        now: datetime,
    ) -> OutboxJob | None:
        job = self._tx.state.outbox_jobs.get(job_id)
        if job is None or job.project_memory_space_id != project_memory_space_id:
            return None
        if job.status not in ("dead_letter",):
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
        self._tx.state.outbox_jobs[job_id] = updated
        return updated

    def _get_locked_job(self, job_id: str, locked_by: str) -> OutboxJob:
        job = self._tx.state.outbox_jobs[job_id]
        if job.status != "processing" or job.locked_by != locked_by:
            raise OutboxLockOwnershipError("outbox job is not locked by this worker")
        return job


def _outbox_job_sort_value(job: OutboxJob, sort: str | None) -> object:
    if sort == "created_at":
        return job.created_at
    if sort == "next_run_at":
        return job.next_run_at
    if sort == "priority":
        return job.priority
    return job.updated_at


def _is_claimable(job: OutboxJob, now: datetime) -> bool:
    if job.status == "pending" and job.next_run_at <= now:
        return True
    return (
        job.status == "processing"
        and job.lock_expires_at is not None
        and job.lock_expires_at <= now
    )
