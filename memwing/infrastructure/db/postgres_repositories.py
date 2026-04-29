from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

from memwing.core.models import AuditEvent, OutboxJob, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import OutboxLockOwnershipError

from .postgres_rows import (
    Row,
    audit_event_from_row,
    outbox_job_from_row,
    source_event_from_row,
)
from .postgres_sql import (
    _CLAIM_OUTBOX_JOBS_SQL,
    _INSERT_AUDIT_EVENT_SQL,
    _INSERT_OUTBOX_JOB_SQL,
    _INSERT_SOURCE_EVENT_SQL,
    _LIST_SOURCE_EVENTS_FOR_SCOPE_SQL,
    _MARK_OUTBOX_FAILED_SQL,
    _MARK_OUTBOX_SUCCEEDED_SQL,
    _SELECT_EXISTING_SOURCE_EVENT_SQL,
)


class PostgresExecutor:
    async def fetchrow(self, sql: str, params: Mapping[str, object]) -> Row | None:
        raise NotImplementedError

    async def fetch(self, sql: str, params: Mapping[str, object]) -> tuple[Row, ...]:
        raise NotImplementedError


class PostgresSourceEventRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def insert_if_absent(self, event: SourceEvent) -> tuple[SourceEvent, bool]:
        params = _source_event_params(event)
        row = await self._executor.fetchrow(_INSERT_SOURCE_EVENT_SQL, params)
        if row is not None:
            return source_event_from_row(row), True

        existing = await self._executor.fetchrow(
            _SELECT_EXISTING_SOURCE_EVENT_SQL,
            {
                "project_memory_space_id": event.project_memory_space_id,
                "raw_payload_hash": event.raw_payload_hash,
                "runtime_event_idempotency_key": event.runtime_event_idempotency_key,
            },
        )
        if existing is None:
            raise RuntimeError("source event insert conflict did not resolve to an existing row")
        return source_event_from_row(existing), False

    async def get_source_event(self, source_event_id: str) -> SourceEvent | None:
        row = await self._executor.fetchrow(
            "SELECT * FROM source_events WHERE id = %(source_event_id)s",
            {"source_event_id": source_event_id},
        )
        return source_event_from_row(row) if row is not None else None

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[SourceEvent, ...]:
        rows = await self._executor.fetch(
            _LIST_SOURCE_EVENTS_FOR_SCOPE_SQL,
            {
                "project_memory_space_id": scope.project_memory_space_id,
                "group_ids": scope.group_ids,
                "thread_id": scope.thread_id,
                "shared_group_id": scope.shared_group_id,
                "limit": limit,
            },
        )
        return tuple(source_event_from_row(row) for row in rows)


class PostgresAuditEventRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def record(self, event: AuditEvent) -> AuditEvent:
        row = await self._executor.fetchrow(
            _INSERT_AUDIT_EVENT_SQL,
            {
                "id": event.id,
                "trace_id": event.trace_id,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "stage": event.stage,
                "input_ref": event.input_ref,
                "output_ref": event.output_ref,
                "decision": event.decision,
                "reason_code": event.reason_code,
                "reason_text": event.reason_text,
                "source_event_ids": event.source_event_ids,
                "latency_ms": event.latency_ms,
                "created_at": event.created_at,
                "actor_id": event.actor_id,
            },
        )
        if row is None:
            raise RuntimeError("audit event insert did not return a row")
        return audit_event_from_row(row)


class PostgresOutboxJobRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def enqueue(self, job: OutboxJob) -> OutboxJob:
        row = await self._executor.fetchrow(_INSERT_OUTBOX_JOB_SQL, _outbox_job_params(job))
        if row is not None:
            return outbox_job_from_row(row)

        existing = await self._executor.fetchrow(
            "SELECT * FROM outbox_jobs WHERE idempotency_key = %(idempotency_key)s",
            {"idempotency_key": job.idempotency_key},
        )
        if existing is None:
            raise RuntimeError("outbox insert conflict did not resolve to an existing row")
        return outbox_job_from_row(existing)

    async def claim_pending(
        self,
        *,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        rows = await self._executor.fetch(
            _CLAIM_OUTBOX_JOBS_SQL,
            {
                "now": now,
                "worker_id": worker_id,
                "lock_expires_at": now + lock_duration,
                "limit": limit,
            },
        )
        return tuple(outbox_job_from_row(row) for row in rows)

    async def mark_succeeded(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
    ) -> OutboxJob:
        row = await self._executor.fetchrow(
            _MARK_OUTBOX_SUCCEEDED_SQL,
            {"job_id": job_id, "locked_by": locked_by, "now": now},
        )
        if row is None:
            raise OutboxLockOwnershipError("outbox job is not locked by this worker")
        return outbox_job_from_row(row)

    async def mark_failed(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
        retry_delay: timedelta,
    ) -> OutboxJob:
        row = await self._executor.fetchrow(
            _MARK_OUTBOX_FAILED_SQL,
            {
                "job_id": job_id,
                "locked_by": locked_by,
                "now": now,
                "last_error": error,
                "retry_at": now + retry_delay,
            },
        )
        if row is None:
            raise OutboxLockOwnershipError("outbox job is not locked by this worker")
        return outbox_job_from_row(row)


def _source_event_params(event: SourceEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "project_memory_space_id": event.project_memory_space_id,
        "group_id": event.group_id,
        "thread_id": event.thread_id,
        "shared_group_id": event.shared_group_id,
        "author_id": event.author_id,
        "author_name": event.author_name,
        "source_type": event.source_type,
        "content": event.content,
        "content_preview": event.content_preview,
        "source_url": event.source_url,
        "event_time": event.event_time,
        "raw_payload_hash": event.raw_payload_hash,
        "runtime_event_idempotency_key": event.runtime_event_idempotency_key,
        "metadata_json": event.metadata,
        "purged_at": event.purged_at,
        "purged_by": event.purged_by,
        "purge_reason": event.purge_reason,
        "purge_level": event.purge_level,
        "graph_backend_raw_retained": event.graph_backend_raw_retained,
        "created_at": event.created_at,
    }


def _outbox_job_params(job: OutboxJob) -> dict[str, object]:
    return {
        "id": job.id,
        "project_memory_space_id": job.project_memory_space_id,
        "source_event_id": job.source_event_id,
        "job_type": job.job_type,
        "payload_json": job.payload_json,
        "status": job.status,
        "idempotency_key": job.idempotency_key,
        "aggregate_key": job.aggregate_key,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "priority": job.priority,
        "next_run_at": job.next_run_at,
        "locked_at": job.locked_at,
        "locked_by": job.locked_by,
        "lock_expires_at": job.lock_expires_at,
        "last_error": job.last_error,
        "dead_letter_reason": job.dead_letter_reason,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }
