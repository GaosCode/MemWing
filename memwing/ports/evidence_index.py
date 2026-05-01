from __future__ import annotations

from typing import Protocol, runtime_checkable

from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult
from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope


@runtime_checkable
class EvidenceIndexPort(Protocol):
    async def index_source_event(self, source_event: SourceEvent, scope: EffectiveScope) -> None:
        ...

    async def search(self, query: MemorySearchQuery) -> MemorySearchResult:
        ...

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        ...
