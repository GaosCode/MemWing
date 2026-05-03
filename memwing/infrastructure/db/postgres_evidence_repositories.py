from __future__ import annotations

from datetime import datetime

from memwing.core.models import EvidenceChunk, WorkingMemoryEntry

from .postgres_derived_rows import evidence_chunk_from_row, working_memory_entry_from_row
from .postgres_derived_sql import (
    _APPEND_WORKING_MEMORY_SQL,
    _COUNT_EVIDENCE_SOURCE_EVENTS_SQL,
    _COUNT_WORKING_MEMORY_SOURCE_EVENTS_SQL,
    _LIST_RECENT_WORKING_MEMORY_SQL,
    _MARK_EVIDENCE_SOURCE_REDACTED_SQL,
    _MARK_WORKING_MEMORY_FLUSHED_SQL,
    _NEXT_WORKING_MEMORY_SEQUENCE_SQL,
    _SUM_UNFLUSHED_WORKING_MEMORY_TOKENS_SQL,
    _UPSERT_EVIDENCE_CHUNK_SQL,
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

    async def count_by_source_events(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
    ) -> int:
        if not source_event_ids:
            return 0
        row = await self._executor.fetchrow(
            _COUNT_EVIDENCE_SOURCE_EVENTS_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "source_event_ids": source_event_ids,
            },
        )
        return _source_event_count(row, "evidence chunk count query did not return an integer")


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

    async def next_sequence(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
    ) -> int:
        row = await self._executor.fetchrow(
            _NEXT_WORKING_MEMORY_SEQUENCE_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "thread_id": thread_id,
            },
        )
        if row is None or not isinstance(row["next_sequence"], int):
            raise RuntimeError("working memory next sequence query did not return an integer")
        return row["next_sequence"]

    async def sum_unflushed_tokens(
        self,
        *,
        project_memory_space_id: str,
        group_id: str | None,
        thread_id: str | None,
    ) -> int:
        row = await self._executor.fetchrow(
            _SUM_UNFLUSHED_WORKING_MEMORY_TOKENS_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "group_id": group_id,
                "thread_id": thread_id,
            },
        )
        if row is None or not isinstance(row["token_count"], int):
            raise RuntimeError("working memory token sum query did not return an integer")
        return row["token_count"]

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

    async def count_by_source_events(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
    ) -> int:
        if not source_event_ids:
            return 0
        row = await self._executor.fetchrow(
            _COUNT_WORKING_MEMORY_SOURCE_EVENTS_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "source_event_ids": source_event_ids,
            },
        )
        return _source_event_count(row, "working memory count query did not return an integer")


def _source_event_count(row: object, error_message: str) -> int:
    if row is None:
        raise RuntimeError(error_message)
    value = row["source_event_count"]
    if not isinstance(value, int):
        raise RuntimeError(error_message)
    return value


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
