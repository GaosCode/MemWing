from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from memwing.core.models import MemoryItem, PageMemory, PageMemorySynthesis, SourceEvent
from memwing.core.scope import EffectiveScope


@dataclass(frozen=True, slots=True)
class PageMemorySynthesisRequest:
    scope: EffectiveScope
    source_events: tuple[SourceEvent, ...]
    existing_page: PageMemory | None
    linked_memory_items: tuple[MemoryItem, ...]


@runtime_checkable
class PageMemorySynthesisPort(Protocol):
    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        ...
