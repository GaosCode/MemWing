from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from memwing.core.models import EvidenceChunk, WorkingMemoryEntry

from .in_memory_transaction_view import InMemoryTransactionView


class InMemoryEvidenceChunkRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert_chunk(self, chunk: EvidenceChunk) -> EvidenceChunk:
        key = (chunk.source_event_id, chunk.chunk_index)
        existing_id = self._tx.state.evidence_by_source_chunk.get(key)
        if existing_id is not None:
            existing = self._tx.state.evidence_chunks[existing_id]
            updated = replace(
                existing,
                chunk_text=chunk.chunk_text,
                embedding_model=chunk.embedding_model,
                embedding_ref=chunk.embedding_ref,
                embedding_vector=chunk.embedding_vector,
                invalidated_at=chunk.invalidated_at,
            )
            self._tx.state.evidence_chunks[existing_id] = updated
            return updated

        self._tx.state.evidence_chunks[chunk.id] = chunk
        self._tx.state.evidence_by_source_chunk[key] = chunk.id
        return chunk

    async def mark_source_redacted(
        self,
        *,
        source_event_id: str,
        invalidated_at: datetime,
    ) -> int:
        count = 0
        for chunk_id, chunk in tuple(self._tx.state.evidence_chunks.items()):
            if chunk.source_event_id == source_event_id and chunk.invalidated_at is None:
                self._tx.state.evidence_chunks[chunk_id] = replace(
                    chunk,
                    invalidated_at=invalidated_at,
                )
                count += 1
        return count


class InMemoryWorkingMemoryRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def append(self, entry: WorkingMemoryEntry) -> WorkingMemoryEntry:
        key = (entry.project_memory_space_id, entry.thread_id, entry.sequence)
        existing_id = self._tx.state.working_memory_by_scope_sequence.get(key)
        if existing_id is not None:
            return self._tx.state.working_memory_entries[existing_id]

        self._tx.state.working_memory_entries[entry.id] = entry
        self._tx.state.working_memory_by_scope_sequence[key] = entry.id
        return entry

    async def list_recent(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        limit: int,
    ) -> tuple[WorkingMemoryEntry, ...]:
        entries = [
            entry
            for entry in self._tx.state.working_memory_entries.values()
            if entry.project_memory_space_id == project_memory_space_id
            and entry.thread_id == thread_id
            and entry.flushed_at is None
        ]
        entries.sort(key=lambda entry: entry.sequence, reverse=True)
        return tuple(entries[:limit])

    async def next_sequence(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
    ) -> int:
        sequences = [
            entry.sequence
            for entry in self._tx.state.working_memory_entries.values()
            if entry.project_memory_space_id == project_memory_space_id
            and entry.thread_id == thread_id
        ]
        return max(sequences, default=0) + 1

    async def sum_unflushed_tokens(
        self,
        *,
        project_memory_space_id: str,
        group_id: str | None,
        thread_id: str | None,
    ) -> int:
        return sum(
            entry.token_count
            for entry in self._tx.state.working_memory_entries.values()
            if entry.project_memory_space_id == project_memory_space_id
            and entry.group_id == group_id
            and entry.thread_id == thread_id
            and entry.flushed_at is None
        )

    async def mark_flushed(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        through_sequence: int,
        flushed_at: datetime,
    ) -> int:
        count = 0
        for entry_id, entry in tuple(self._tx.state.working_memory_entries.items()):
            if (
                entry.project_memory_space_id == project_memory_space_id
                and entry.thread_id == thread_id
                and entry.sequence <= through_sequence
                and entry.flushed_at is None
            ):
                self._tx.state.working_memory_entries[entry_id] = replace(
                    entry,
                    flushed_at=flushed_at,
                )
                count += 1
        return count
