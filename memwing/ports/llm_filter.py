from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from memwing.core.models import (
    EvidenceChunk,
    LongTermFilterItem,
    MemoryItem,
    PageMemory,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope


@dataclass(frozen=True, slots=True)
class LongTermFilterRequest:
    scope: EffectiveScope
    source_events: tuple[SourceEvent, ...]
    recent_page_memory: PageMemory | None
    history_items: tuple[MemoryItem, ...]
    evidence_snippets: tuple[EvidenceChunk, ...]
    trace_id: str | None


@runtime_checkable
class LongTermFilterPort(Protocol):
    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        ...
