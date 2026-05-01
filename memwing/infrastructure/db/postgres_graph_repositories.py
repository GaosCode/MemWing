from __future__ import annotations

from datetime import datetime, timedelta

from memwing.core.models import GraphWriteJob, MemoryGraphLink
from memwing.ports.event_store import OutboxLockOwnershipError

from .postgres_derived_rows import graph_write_job_from_row, memory_graph_link_from_row
from .postgres_derived_sql import (
    _CLAIM_GRAPH_WRITE_JOBS_SQL,
    _EXTEND_GRAPH_WRITE_LOCK_SQL,
    _INSERT_GRAPH_WRITE_JOB_SQL,
    _LIST_GRAPH_WRITE_JOBS_FOR_PROJECT_SQL,
    _LIST_MEMORY_GRAPH_LINKS_BY_MEMORY_SQL,
    _MARK_GRAPH_WRITE_DEAD_LETTER_SQL,
    _MARK_GRAPH_WRITE_FAILED_SQL,
    _MARK_GRAPH_WRITE_SUCCEEDED_SQL,
    _UPSERT_MEMORY_GRAPH_LINK_SQL,
)
from .postgres_repositories import PostgresExecutor


class PostgresGraphWriteJobRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def enqueue(self, job: GraphWriteJob) -> GraphWriteJob:
        row = await self._executor.fetchrow(_INSERT_GRAPH_WRITE_JOB_SQL, _graph_write_job_params(job))
        if row is not None:
            return graph_write_job_from_row(row)

        existing = await self._executor.fetchrow(
            "SELECT * FROM graph_write_jobs WHERE idempotency_key = %(idempotency_key)s",
            {"idempotency_key": job.idempotency_key},
        )
        if existing is None:
            raise RuntimeError("graph write job conflict did not resolve to an existing row")
        return graph_write_job_from_row(existing)

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[GraphWriteJob, ...]:
        rows = await self._executor.fetch(
            _LIST_GRAPH_WRITE_JOBS_FOR_PROJECT_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "limit": limit,
            },
        )
        return tuple(graph_write_job_from_row(row) for row in rows)

    async def claim_pending(
        self,
        *,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[GraphWriteJob, ...]:
        rows = await self._executor.fetch(
            _CLAIM_GRAPH_WRITE_JOBS_SQL,
            {
                "now": now,
                "worker_id": worker_id,
                "lock_expires_at": now + lock_duration,
                "limit": limit,
            },
        )
        return tuple(graph_write_job_from_row(row) for row in rows)

    async def mark_succeeded(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
    ) -> GraphWriteJob:
        row = await self._executor.fetchrow(
            _MARK_GRAPH_WRITE_SUCCEEDED_SQL,
            {
                "job_id": job_id,
                "locked_by": locked_by,
                "now": now,
            },
        )
        if row is None:
            raise OutboxLockOwnershipError("graph write job is not locked by this worker")
        return graph_write_job_from_row(row)

    async def extend_lock(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        lock_duration: timedelta,
    ) -> GraphWriteJob:
        row = await self._executor.fetchrow(
            _EXTEND_GRAPH_WRITE_LOCK_SQL,
            {
                "job_id": job_id,
                "locked_by": locked_by,
                "now": now,
                "lock_expires_at": now + lock_duration,
            },
        )
        if row is None:
            raise OutboxLockOwnershipError("graph write job is not locked by this worker")
        return graph_write_job_from_row(row)

    async def mark_failed(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
        retry_delay: timedelta,
    ) -> GraphWriteJob:
        row = await self._executor.fetchrow(
            _MARK_GRAPH_WRITE_FAILED_SQL,
            {
                "job_id": job_id,
                "locked_by": locked_by,
                "now": now,
                "last_error": error,
                "retry_at": now + retry_delay,
            },
        )
        if row is None:
            raise OutboxLockOwnershipError("graph write job is not locked by this worker")
        return graph_write_job_from_row(row)

    async def mark_dead_letter(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
    ) -> GraphWriteJob:
        row = await self._executor.fetchrow(
            _MARK_GRAPH_WRITE_DEAD_LETTER_SQL,
            {
                "job_id": job_id,
                "locked_by": locked_by,
                "now": now,
                "last_error": error,
            },
        )
        if row is None:
            raise OutboxLockOwnershipError("graph write job is not locked by this worker")
        return graph_write_job_from_row(row)


class PostgresMemoryGraphLinkRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def upsert(self, link: MemoryGraphLink) -> MemoryGraphLink:
        row = await self._executor.fetchrow(_UPSERT_MEMORY_GRAPH_LINK_SQL, _memory_graph_link_params(link))
        if row is not None:
            return memory_graph_link_from_row(row)

        existing = await self._executor.fetchrow(
            """
            SELECT *
            FROM memory_graph_links
            WHERE backend = %(backend)s
              AND backend_object_type = %(backend_object_type)s
              AND backend_object_id = %(backend_object_id)s
              AND memory_id = %(memory_id)s
              AND link_type = %(link_type)s
            """,
            {
                "backend": link.backend,
                "backend_object_type": link.backend_object_type,
                "backend_object_id": link.backend_object_id,
                "memory_id": link.memory_id,
                "link_type": link.link_type,
            },
        )
        if existing is None:
            raise RuntimeError("memory graph link conflict did not resolve to an existing row")
        return memory_graph_link_from_row(existing)

    async def list_by_memory(self, memory_id: str) -> tuple[MemoryGraphLink, ...]:
        rows = await self._executor.fetch(
            _LIST_MEMORY_GRAPH_LINKS_BY_MEMORY_SQL,
            {"memory_id": memory_id},
        )
        return tuple(memory_graph_link_from_row(row) for row in rows)


def _graph_write_job_params(job: GraphWriteJob) -> dict[str, object]:
    return {
        "id": job.id,
        "backend": job.backend,
        "project_memory_space_id": job.project_memory_space_id,
        "thread_id": job.thread_id,
        "saga_id": job.saga_id,
        "memory_id": job.memory_id,
        "source_event_ids": job.source_event_ids,
        "route": job.route,
        "status": job.status,
        "idempotency_key": job.idempotency_key,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "priority": job.priority,
        "next_run_at": job.next_run_at,
        "dead_letter_reason": job.dead_letter_reason,
        "last_error": job.last_error,
        "locked_at": job.locked_at,
        "locked_by": job.locked_by,
        "lock_expires_at": job.lock_expires_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _memory_graph_link_params(link: MemoryGraphLink) -> dict[str, object]:
    return {
        "id": link.id,
        "backend": link.backend,
        "memory_id": link.memory_id,
        "source_event_id": link.source_event_id,
        "project_memory_space_id": link.project_memory_space_id,
        "backend_space_id": link.backend_space_id,
        "backend_object_type": link.backend_object_type,
        "backend_object_id": link.backend_object_id,
        "link_type": link.link_type,
        "created_at": link.created_at,
    }
