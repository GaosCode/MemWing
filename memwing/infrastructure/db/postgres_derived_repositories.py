from __future__ import annotations

from datetime import datetime, timedelta

from memwing.core.models import (
    EvidenceChunk,
    GraphWriteJob,
    MemoryGraphLink,
    MemoryItem,
    MemoryPageVersion,
    MemoryVersion,
    PageMemory,
    PageMemoryScopeType,
    WorkingMemoryEntry,
)
from memwing.ports.event_store import OutboxLockOwnershipError

from .postgres_derived_rows import (
    evidence_chunk_from_row,
    graph_write_job_from_row,
    memory_graph_link_from_row,
    memory_item_from_row,
    memory_page_version_from_row,
    memory_version_from_row,
    page_memory_from_row,
    working_memory_entry_from_row,
)
from .postgres_derived_sql import (
    _APPEND_WORKING_MEMORY_SQL,
    _CLAIM_GRAPH_WRITE_JOBS_SQL,
    _GET_MEMORY_ITEM_SQL,
    _GET_MEMORY_PAGE_BY_SCOPE_SQL,
    _INSERT_GRAPH_WRITE_JOB_SQL,
    _INSERT_MEMORY_PAGE_VERSION_SQL,
    _INSERT_MEMORY_VERSION_SQL,
    _LIST_MEMORY_GRAPH_LINKS_BY_MEMORY_SQL,
    _LIST_MEMORY_ITEMS_BY_SOURCE_SQL,
    _LIST_RECENT_WORKING_MEMORY_SQL,
    _MARK_EVIDENCE_SOURCE_REDACTED_SQL,
    _MARK_GRAPH_WRITE_FAILED_SQL,
    _MARK_GRAPH_WRITE_SUCCEEDED_SQL,
    _MARK_MEMORY_PAGES_REBUILD_FOR_SOURCE_SQL,
    _MARK_WORKING_MEMORY_FLUSHED_SQL,
    _UPSERT_EVIDENCE_CHUNK_SQL,
    _UPSERT_MEMORY_GRAPH_LINK_SQL,
    _UPSERT_MEMORY_ITEM_SQL,
    _UPSERT_MEMORY_PAGE_SQL,
)
from .postgres_repositories import PostgresExecutor


class PostgresEvidenceChunkRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def upsert_chunk(self, chunk: EvidenceChunk) -> EvidenceChunk:
        row = await self._executor.fetchrow(_UPSERT_EVIDENCE_CHUNK_SQL, _evidence_chunk_params(chunk))
        if row is None:
            raise RuntimeError("evidence chunk upsert did not return a row")
        return evidence_chunk_from_row(row)

    async def mark_source_redacted(
        self,
        *,
        source_event_id: str,
        invalidated_at: datetime,
    ) -> int:
        rows = await self._executor.fetch(
            _MARK_EVIDENCE_SOURCE_REDACTED_SQL,
            {
                "source_event_id": source_event_id,
                "invalidated_at": invalidated_at,
            },
        )
        return len(rows)


class PostgresWorkingMemoryRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def append(self, entry: WorkingMemoryEntry) -> WorkingMemoryEntry:
        row = await self._executor.fetchrow(_APPEND_WORKING_MEMORY_SQL, _working_memory_params(entry))
        if row is not None:
            return working_memory_entry_from_row(row)

        existing = await self._executor.fetchrow(
            """
            SELECT *
            FROM working_memory_entries
            WHERE project_memory_space_id = %(project_memory_space_id)s
              AND thread_id IS NOT DISTINCT FROM %(thread_id)s
              AND sequence = %(sequence)s
            """,
            {
                "project_memory_space_id": entry.project_memory_space_id,
                "thread_id": entry.thread_id,
                "sequence": entry.sequence,
            },
        )
        if existing is None:
            raise RuntimeError("working memory insert conflict did not resolve to an existing row")
        return working_memory_entry_from_row(existing)

    async def list_recent(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        limit: int,
    ) -> tuple[WorkingMemoryEntry, ...]:
        rows = await self._executor.fetch(
            _LIST_RECENT_WORKING_MEMORY_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "thread_id": thread_id,
                "limit": limit,
            },
        )
        return tuple(working_memory_entry_from_row(row) for row in rows)

    async def mark_flushed(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        through_sequence: int,
        flushed_at: datetime,
    ) -> int:
        rows = await self._executor.fetch(
            _MARK_WORKING_MEMORY_FLUSHED_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "thread_id": thread_id,
                "through_sequence": through_sequence,
                "flushed_at": flushed_at,
            },
        )
        return len(rows)


class PostgresMemoryItemRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def upsert(self, item: MemoryItem) -> MemoryItem:
        row = await self._executor.fetchrow(_UPSERT_MEMORY_ITEM_SQL, _memory_item_params(item))
        if row is None:
            raise RuntimeError("memory item upsert did not return a row")
        return memory_item_from_row(row)

    async def get(self, memory_id: str) -> MemoryItem | None:
        row = await self._executor.fetchrow(_GET_MEMORY_ITEM_SQL, {"memory_id": memory_id})
        return memory_item_from_row(row) if row is not None else None

    async def list_by_source_event(self, source_event_id: str) -> tuple[MemoryItem, ...]:
        rows = await self._executor.fetch(
            _LIST_MEMORY_ITEMS_BY_SOURCE_SQL,
            {"source_event_id": source_event_id},
        )
        return tuple(memory_item_from_row(row) for row in rows)


class PostgresMemoryVersionRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def record(self, version: MemoryVersion) -> MemoryVersion:
        row = await self._executor.fetchrow(_INSERT_MEMORY_VERSION_SQL, _memory_version_params(version))
        if row is not None:
            return memory_version_from_row(row)

        existing = await self._executor.fetchrow(
            """
            SELECT *
            FROM memory_versions
            WHERE memory_id = %(memory_id)s
              AND version = %(version)s
            """,
            {
                "memory_id": version.memory_id,
                "version": version.version,
            },
        )
        if existing is None:
            raise RuntimeError("memory version insert conflict did not resolve to an existing row")
        return memory_version_from_row(existing)


class PostgresMemoryPageRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def upsert(self, page: PageMemory) -> PageMemory:
        row = await self._executor.fetchrow(_UPSERT_MEMORY_PAGE_SQL, _page_memory_params(page))
        if row is None:
            raise RuntimeError("memory page upsert did not return a row")
        return page_memory_from_row(row)

    async def get_by_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> PageMemory | None:
        row = await self._executor.fetchrow(
            _GET_MEMORY_PAGE_BY_SCOPE_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
            },
        )
        return page_memory_from_row(row) if row is not None else None

    async def mark_needs_rebuild_for_source(
        self,
        *,
        source_event_id: str,
        updated_at: datetime,
    ) -> int:
        rows = await self._executor.fetch(
            _MARK_MEMORY_PAGES_REBUILD_FOR_SOURCE_SQL,
            {
                "source_event_id": source_event_id,
                "updated_at": updated_at,
            },
        )
        return len(rows)


class PostgresMemoryPageVersionRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def record(self, version: MemoryPageVersion) -> MemoryPageVersion:
        row = await self._executor.fetchrow(
            _INSERT_MEMORY_PAGE_VERSION_SQL,
            _memory_page_version_params(version),
        )
        if row is not None:
            return memory_page_version_from_row(row)

        existing = await self._executor.fetchrow(
            """
            SELECT *
            FROM memory_page_versions
            WHERE page_id = %(page_id)s
              AND version = %(version)s
            """,
            {
                "page_id": version.page_id,
                "version": version.version,
            },
        )
        if existing is None:
            raise RuntimeError("memory page version conflict did not resolve to an existing row")
        return memory_page_version_from_row(existing)


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


def _evidence_chunk_params(chunk: EvidenceChunk) -> dict[str, object]:
    return {
        "id": chunk.id,
        "source_event_id": chunk.source_event_id,
        "project_memory_space_id": chunk.project_memory_space_id,
        "group_id": chunk.group_id,
        "thread_id": chunk.thread_id,
        "shared_group_id": chunk.shared_group_id,
        "chunk_text": chunk.chunk_text,
        "chunk_index": chunk.chunk_index,
        "embedding_model": chunk.embedding_model,
        "embedding_ref": chunk.embedding_ref,
        "embedding_vector": chunk.embedding_vector,
        "invalidated_at": chunk.invalidated_at,
        "created_at": chunk.created_at,
    }


def _working_memory_params(entry: WorkingMemoryEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "source_event_id": entry.source_event_id,
        "project_memory_space_id": entry.project_memory_space_id,
        "group_id": entry.group_id,
        "thread_id": entry.thread_id,
        "shared_group_id": entry.shared_group_id,
        "content": entry.content,
        "token_count": entry.token_count,
        "sequence": entry.sequence,
        "flushed_at": entry.flushed_at,
        "created_at": entry.created_at,
    }


def _memory_item_params(item: MemoryItem) -> dict[str, object]:
    return {
        "id": item.id,
        "project_memory_space_id": item.project_memory_space_id,
        "group_id": item.group_id,
        "thread_id": item.thread_id,
        "shared_group_id": item.shared_group_id,
        "route": item.route,
        "display_type": item.display_type,
        "title": item.title,
        "content": item.content,
        "summary": item.summary,
        "source_event_ids": item.source_event_ids,
        "primary_source_event_id": item.primary_source_event_id,
        "status": item.status,
        "event_time": item.event_time,
        "valid_from": item.valid_from,
        "valid_to": item.valid_to,
        "original_score": item.original_score,
        "half_life_days": item.half_life_days,
        "last_reviewed_at": item.last_reviewed_at,
        "last_confirmed_at": item.last_confirmed_at,
        "last_recalled_at": item.last_recalled_at,
        "recall_count": item.recall_count,
        "cached_decayed_score": item.cached_decayed_score,
        "last_decay_computed_at": item.last_decay_computed_at,
        "pinned": item.pinned,
        "created_by": item.created_by,
        "activated_at": item.activated_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "archived_at": item.archived_at,
        "hidden_at": item.hidden_at,
        "invalidated_at": item.invalidated_at,
        "removed_at": item.removed_at,
    }


def _memory_version_params(version: MemoryVersion) -> dict[str, object]:
    return {
        "id": version.id,
        "memory_id": version.memory_id,
        "version": version.version,
        "title": version.title,
        "content": version.content,
        "summary": version.summary,
        "status": version.status,
        "source_event_ids": version.source_event_ids,
        "changed_by": version.changed_by,
        "change_reason": version.change_reason,
        "created_at": version.created_at,
    }


def _page_memory_params(page: PageMemory) -> dict[str, object]:
    return {
        "id": page.id,
        "project_memory_space_id": page.project_memory_space_id,
        "group_id": page.group_id,
        "thread_id": page.thread_id,
        "shared_group_id": page.shared_group_id,
        "scope_type": page.scope_type,
        "scope_id": page.scope_id,
        "title": page.title,
        "brief": page.brief,
        "source_event_ids": page.source_event_ids,
        "linked_memory_item_ids": page.linked_memory_item_ids,
        "version": page.version,
        "needs_rebuild": page.needs_rebuild,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
    }


def _memory_page_version_params(version: MemoryPageVersion) -> dict[str, object]:
    return {
        "id": version.id,
        "page_id": version.page_id,
        "version": version.version,
        "title": version.title,
        "brief": version.brief,
        "source_event_ids": version.source_event_ids,
        "linked_memory_item_ids": version.linked_memory_item_ids,
        "changed_by": version.changed_by,
        "change_reason": version.change_reason,
        "created_at": version.created_at,
    }


def _graph_write_job_params(job: GraphWriteJob) -> dict[str, object]:
    return {
        "id": job.id,
        "backend": job.backend,
        "project_memory_space_id": job.project_memory_space_id,
        "thread_id": job.thread_id,
        "saga_id": job.saga_id,
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
