from __future__ import annotations

from datetime import datetime

from memwing.core.models import (
    MemoryItem,
    MemoryPageVersion,
    MemoryVersion,
    PageMemory,
    PageMemoryScopeType,
)

from .postgres_derived_rows import (
    memory_item_from_row,
    memory_page_version_from_row,
    memory_version_from_row,
    page_memory_from_row,
)
from .postgres_derived_sql import (
    _GET_MEMORY_ITEM_SQL,
    _GET_MEMORY_PAGE_BY_SCOPE_SQL,
    _INSERT_MEMORY_PAGE_VERSION_SQL,
    _INSERT_MEMORY_VERSION_SQL,
    _LIST_MEMORY_ITEMS_BY_SOURCE_SQL,
    _MARK_MEMORY_PAGES_REBUILD_FOR_SOURCE_SQL,
    _UPSERT_MEMORY_ITEM_SQL,
    _UPSERT_MEMORY_PAGE_SQL,
)
from .postgres_repositories import PostgresExecutor


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
