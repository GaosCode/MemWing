from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from memwing.core.models import (
    GraphWriteJob,
    GraphWriteResult,
    MemoryItem,
    SourceEvent,
)
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult
from memwing.core.scope import EffectiveScope


@dataclass(frozen=True, slots=True)
class GraphWriteRequest:
    job: GraphWriteJob
    memory_item: MemoryItem
    source_events: tuple[SourceEvent, ...]


@runtime_checkable
class GraphBackendPort(Protocol):
    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        ...

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        ...

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        ...

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        ...
