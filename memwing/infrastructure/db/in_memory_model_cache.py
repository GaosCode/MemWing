from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from memwing.ports.model_result_cache import ModelResultCacheEntry, ModelResultCacheKey

from .in_memory_transaction_view import InMemoryTransactionView


class InMemoryModelResultCacheRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def get(
        self,
        *,
        key: ModelResultCacheKey,
        now: datetime,
    ) -> ModelResultCacheEntry | None:
        entry_id = self._tx.state.model_result_cache_by_key.get(key)
        if entry_id is None:
            return None
        entry = self._tx.state.model_result_cache[entry_id]
        if entry.status != "active":
            return None
        if entry.expires_at is not None and entry.expires_at <= now:
            return None
        updated = replace(entry, last_hit_at=now, hit_count=entry.hit_count + 1)
        self._tx.state.model_result_cache[entry.id] = updated
        return updated

    async def put(self, entry: ModelResultCacheEntry) -> ModelResultCacheEntry:
        existing_id = self._tx.state.model_result_cache_by_key.get(entry.key)
        if existing_id is not None:
            existing = self._tx.state.model_result_cache[existing_id]
            entry = replace(
                entry,
                id=existing_id,
                source_event_ids=_merge_source_event_ids(
                    existing.source_event_ids,
                    entry.source_event_ids,
                ),
            )
        self._tx.state.model_result_cache[entry.id] = entry
        self._tx.state.model_result_cache_by_key[entry.key] = entry.id
        return entry

    async def list_by_source_event(
        self,
        *,
        project_memory_space_id: str,
        source_event_id: str,
    ) -> tuple[ModelResultCacheEntry, ...]:
        return tuple(
            entry
            for entry in self._tx.state.model_result_cache.values()
            if entry.key.project_memory_space_id == project_memory_space_id
            and source_event_id in entry.source_event_ids
        )

    async def invalidate_source_event(
        self,
        *,
        project_memory_space_id: str,
        source_event_id: str,
        invalidated_at: datetime,
        reason: str,
    ) -> int:
        count = 0
        for entry in tuple(self._tx.state.model_result_cache.values()):
            if entry.key.project_memory_space_id != project_memory_space_id:
                continue
            if source_event_id not in entry.source_event_ids:
                continue
            if entry.status == "invalidated":
                continue
            self._tx.state.model_result_cache[entry.id] = replace(
                entry,
                status="invalidated",
                invalidated_at=invalidated_at,
                invalidated_reason=reason,
            )
            count += 1
        return count


def _merge_source_event_ids(
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(sorted({*first, *second}))
