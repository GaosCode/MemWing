from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from memwing.core.models import (
    MemoryItem,
    MemoryPageVersion,
    MemoryVersion,
    PageMemory,
    PageMemoryScopeType,
)
from memwing.core.scope import EffectiveScope

from .in_memory_scope import effective_scope_matches
from .in_memory_transaction_view import InMemoryTransactionView


class InMemoryMemoryItemRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert(self, item: MemoryItem) -> MemoryItem:
        self._tx.state.memory_items[item.id] = item
        return item

    async def get(self, memory_id: str) -> MemoryItem | None:
        return self._tx.state.memory_items.get(memory_id)

    async def get_for_update(self, memory_id: str) -> MemoryItem | None:
        return await self.get(memory_id)

    async def list_by_source_event(self, source_event_id: str) -> tuple[MemoryItem, ...]:
        return tuple(
            item
            for item in self._tx.state.memory_items.values()
            if source_event_id in item.source_event_ids
        )

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[MemoryItem, ...]:
        items = [
            item
            for item in self._tx.state.memory_items.values()
            if item.project_memory_space_id == scope.project_memory_space_id
            and effective_scope_matches(
                group_id=item.group_id,
                thread_id=item.thread_id,
                shared_group_id=item.shared_group_id,
                scope=scope,
            )
        ]
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return tuple(items[:limit])


class InMemoryMemoryVersionRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def record(self, version: MemoryVersion) -> MemoryVersion:
        key = (version.memory_id, version.version)
        existing_id = self._tx.state.memory_version_by_memory_version.get(key)
        if existing_id is not None:
            return self._tx.state.memory_versions[existing_id]

        self._tx.state.memory_versions[version.id] = version
        self._tx.state.memory_version_by_memory_version[key] = version.id
        return version

    async def get_latest(self, memory_id: str) -> MemoryVersion | None:
        versions = [
            version
            for version in self._tx.state.memory_versions.values()
            if version.memory_id == memory_id
        ]
        versions.sort(key=lambda version: version.version, reverse=True)
        return versions[0] if versions else None


class InMemoryMemoryPageRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert(self, page: PageMemory) -> PageMemory:
        key = (page.project_memory_space_id, page.scope_type, page.scope_id)
        existing_id = self._tx.state.memory_page_by_scope.get(key)
        if existing_id is not None:
            existing = self._tx.state.memory_pages[existing_id]
            updated = replace(
                existing,
                group_id=page.group_id,
                thread_id=page.thread_id,
                shared_group_id=page.shared_group_id,
                title=page.title,
                brief=page.brief,
                topics=page.topics,
                open_questions=page.open_questions,
                next_steps=page.next_steps,
                source_event_ids=page.source_event_ids,
                linked_memory_item_ids=page.linked_memory_item_ids,
                version=page.version,
                needs_rebuild=page.needs_rebuild,
                created_at=page.created_at,
                updated_at=page.updated_at,
            )
            self._tx.state.memory_pages[existing_id] = updated
            return updated

        self._tx.state.memory_pages[page.id] = page
        self._tx.state.memory_page_by_scope[key] = page.id
        return page

    async def get_by_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> PageMemory | None:
        page_id = self._tx.state.memory_page_by_scope.get(
            (project_memory_space_id, scope_type, scope_id)
        )
        if page_id is None:
            return None
        return self._tx.state.memory_pages[page_id]

    async def mark_needs_rebuild_for_source(
        self,
        *,
        source_event_id: str,
        updated_at: datetime,
    ) -> int:
        count = 0
        for page_id, page in tuple(self._tx.state.memory_pages.items()):
            if source_event_id in page.source_event_ids and not page.needs_rebuild:
                self._tx.state.memory_pages[page_id] = replace(
                    page,
                    needs_rebuild=True,
                    updated_at=updated_at,
                )
                count += 1
        return count

    async def list_needs_rebuild(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PageMemory, ...]:
        pages = [
            page
            for page in self._tx.state.memory_pages.values()
            if page.project_memory_space_id == project_memory_space_id and page.needs_rebuild
        ]
        pages.sort(key=lambda page: (page.updated_at, page.id))
        return tuple(pages[:limit])


class InMemoryMemoryPageVersionRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def record(self, version: MemoryPageVersion) -> MemoryPageVersion:
        key = (version.page_id, version.version)
        existing_id = self._tx.state.memory_page_version_by_page_version.get(key)
        if existing_id is not None:
            return self._tx.state.memory_page_versions[existing_id]

        self._tx.state.memory_page_versions[version.id] = version
        self._tx.state.memory_page_version_by_page_version[key] = version.id
        return version
