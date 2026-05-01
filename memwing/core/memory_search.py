from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from memwing.core.scope import EffectiveScope


MemorySearchMode = Literal["current", "history"]
MemorySearchSort = Literal["relevance", "event_time", "updated_at"]
MemorySearchResultSource = Literal[
    "graph",
    "memory_item",
    "page_memory",
    "evidence",
    "working_memory",
    "raw_event",
]


@dataclass(frozen=True, slots=True)
class MemorySearchQuery:
    query: str
    scope: EffectiveScope
    mode: MemorySearchMode = "current"
    limit: int = 20
    cursor: str | None = None
    sort: MemorySearchSort = "relevance"
    min_score: float = 0
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemorySearchResultItem:
    id: str
    text: str
    score: float | None
    source: MemorySearchResultSource
    source_event_ids: tuple[str, ...]
    memory_item_ids: tuple[str, ...]
    valid_from: datetime | None
    valid_to: datetime | None
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    contexts: tuple[str, ...]
    results: tuple[MemorySearchResultItem, ...]
    next_cursor: str | None
    trace_id: str
