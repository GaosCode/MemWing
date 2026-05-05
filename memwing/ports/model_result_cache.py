from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from memwing.ports.model_runtime import MemWingModelRole, MemWingModelRuntime, MemWingModelTransport


ModelResultCacheKind = Literal["embedding", "llm_json"]
ModelResultCacheStatus = Literal["active", "invalidated"]


@dataclass(frozen=True, slots=True)
class ModelResultCacheKey:
    project_memory_space_id: str
    cache_kind: ModelResultCacheKind
    role: MemWingModelRole
    runtime: MemWingModelRuntime
    model: str
    transport: MemWingModelTransport
    prompt_hash: str
    input_hash: str
    schema_hash: str


@dataclass(frozen=True, slots=True)
class ModelResultCacheEntry:
    id: str
    key: ModelResultCacheKey
    source_event_ids: tuple[str, ...]
    value_json: dict[str, object]
    embedding_vector: tuple[float, ...] | None
    status: ModelResultCacheStatus
    created_at: datetime
    last_hit_at: datetime | None
    hit_count: int
    invalidated_at: datetime | None
    invalidated_reason: str | None
    expires_at: datetime | None


class ModelResultCachePort(Protocol):
    async def get(
        self,
        *,
        key: ModelResultCacheKey,
        now: datetime,
    ) -> ModelResultCacheEntry | None:
        ...

    async def put(self, entry: ModelResultCacheEntry) -> ModelResultCacheEntry:
        ...

    async def list_by_source_event(
        self,
        *,
        project_memory_space_id: str,
        source_event_id: str,
    ) -> tuple[ModelResultCacheEntry, ...]:
        ...

    async def invalidate_source_event(
        self,
        *,
        project_memory_space_id: str,
        source_event_id: str,
        invalidated_at: datetime,
        reason: str,
    ) -> int:
        ...
