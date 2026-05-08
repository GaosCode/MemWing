from __future__ import annotations

from datetime import datetime
from typing import Protocol

from memwing.core.models import (
    EvidenceChunk,
    MemoryItem,
    MemoryPageVersion,
    MemoryRecallEvent,
    MemoryVersion,
    PageMemory,
    PageMemoryScopeType,
    WorkingMemoryEntry,
)
from memwing.core.scope import EffectiveScope


class EvidenceChunkRepositoryPort(Protocol):
    async def upsert_chunk(self, chunk: EvidenceChunk) -> EvidenceChunk:
        ...

    async def mark_source_redacted(
        self,
        *,
        source_event_id: str,
        invalidated_at: datetime,
    ) -> int:
        ...

    async def count_by_source_events(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
    ) -> int:
        ...


class WorkingMemoryRepositoryPort(Protocol):
    async def append(self, entry: WorkingMemoryEntry) -> WorkingMemoryEntry:
        ...

    async def list_recent(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        limit: int,
    ) -> tuple[WorkingMemoryEntry, ...]:
        ...

    async def next_sequence(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
    ) -> int:
        ...

    async def sum_unflushed_tokens(
        self,
        *,
        project_memory_space_id: str,
        group_id: str | None,
        thread_id: str | None,
    ) -> int:
        ...

    async def mark_flushed(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        through_sequence: int,
        flushed_at: datetime,
    ) -> int:
        ...

    async def count_by_source_events(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
    ) -> int:
        ...


class MemoryRecallEventRepositoryPort(Protocol):
    async def record(self, event: MemoryRecallEvent) -> MemoryRecallEvent:
        ...


class MemoryItemRepositoryPort(Protocol):
    async def upsert(self, item: MemoryItem) -> MemoryItem:
        ...

    async def get(self, memory_id: str) -> MemoryItem | None:
        ...

    async def get_for_update(self, memory_id: str) -> MemoryItem | None:
        ...

    async def list_by_source_event(self, source_event_id: str) -> tuple[MemoryItem, ...]:
        ...

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        sort: str | None = None,
    ) -> tuple[MemoryItem, ...]:
        ...

    async def list_decay_candidates(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[MemoryItem, ...]:
        ...


class MemoryVersionRepositoryPort(Protocol):
    async def record(self, version: MemoryVersion) -> MemoryVersion:
        ...

    async def get_latest(self, memory_id: str) -> MemoryVersion | None:
        ...

    async def get(self, memory_id: str, version: int) -> MemoryVersion | None:
        ...

    async def list_by_memory(
        self,
        *,
        memory_id: str,
        limit: int,
    ) -> tuple[MemoryVersion, ...]:
        ...


class MemoryPageRepositoryPort(Protocol):
    async def upsert(self, page: PageMemory) -> PageMemory:
        ...

    async def lock_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> None:
        ...

    async def get_by_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> PageMemory | None:
        ...

    async def get_by_scope_for_update(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> PageMemory | None:
        ...

    async def get(self, page_id: str) -> PageMemory | None:
        ...

    async def get_for_update(self, page_id: str) -> PageMemory | None:
        ...

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        sort: str | None = None,
    ) -> tuple[PageMemory, ...]:
        ...

    async def mark_needs_rebuild_for_source(
        self,
        *,
        source_event_id: str,
        updated_at: datetime,
    ) -> int:
        ...

    async def list_needs_rebuild(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PageMemory, ...]:
        ...


class MemoryPageVersionRepositoryPort(Protocol):
    async def record(self, version: MemoryPageVersion) -> MemoryPageVersion:
        ...

    async def get(self, page_id: str, version: int) -> MemoryPageVersion | None:
        ...

    async def list_by_page(
        self,
        *,
        page_id: str,
        limit: int,
    ) -> tuple[MemoryPageVersion, ...]:
        ...
