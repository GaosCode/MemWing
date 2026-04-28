from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.types import JsonObject
from memwing.api.validation import (
    SchemaValidationError,
    require_non_negative_float,
    require_positive_int,
    require_text,
)
from memwing.core.scope import MemoryScope


SortOrder = Literal["relevance", "event_time", "updated_at"]
AgentMemoryMode = Literal["current", "history"]
AgentMemoryResultSource = Literal[
    "graph",
    "memory_item",
    "page_memory",
    "evidence",
    "working_memory",
]


@dataclass(frozen=True, slots=True)
class AgentMemoryQuery:
    runtime_ref: AgentRuntimeRef
    query: str
    scope: MemoryScope
    mode: AgentMemoryMode = "current"
    limit: int = 20
    cursor: str | None = None
    sort: SortOrder = "relevance"
    min_score: float = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", require_text(self.query, "query"))
        if self.mode not in ("current", "history"):
            raise SchemaValidationError("mode must be current or history")
        object.__setattr__(self, "limit", require_positive_int(self.limit, "limit"))
        if self.cursor is not None:
            object.__setattr__(self, "cursor", require_text(self.cursor, "cursor"))
        if self.sort not in ("relevance", "event_time", "updated_at"):
            raise SchemaValidationError("sort must be relevance, event_time, or updated_at")
        object.__setattr__(
            self,
            "min_score",
            require_non_negative_float(self.min_score, "min_score"),
        )


@dataclass(frozen=True, slots=True)
class AgentMemoryResultItem:
    id: str
    text: str
    score: float | None
    source: AgentMemoryResultSource
    source_event_ids: tuple[str, ...]
    memory_item_ids: tuple[str, ...]
    valid_from: datetime | None
    valid_to: datetime | None
    metadata: JsonObject

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_text(self.id, "id"))
        object.__setattr__(self, "text", require_text(self.text, "text"))
        if self.source not in (
            "graph",
            "memory_item",
            "page_memory",
            "evidence",
            "working_memory",
        ):
            raise SchemaValidationError("source is not a supported memory result source")
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))
        object.__setattr__(self, "memory_item_ids", tuple(self.memory_item_ids))


@dataclass(frozen=True, slots=True)
class AgentMemorySearchResult:
    contexts: tuple[str, ...]
    results: tuple[AgentMemoryResultItem, ...]
    next_cursor: str | None
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "contexts", tuple(self.contexts))
        object.__setattr__(self, "results", tuple(self.results))
        if self.next_cursor is not None:
            object.__setattr__(
                self,
                "next_cursor",
                require_text(self.next_cursor, "next_cursor"),
            )
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


@dataclass(frozen=True, slots=True)
class OpenClawNativeMemorySearchRequest:
    runtime_ref: AgentRuntimeRef
    query: str
    scope: MemoryScope
    max_results: int = 20
    mode: AgentMemoryMode = "current"
    min_score: float = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", require_text(self.query, "query"))
        if self.mode not in ("current", "history"):
            raise SchemaValidationError("mode must be current or history")
        object.__setattr__(
            self,
            "max_results",
            require_positive_int(self.max_results, "max_results"),
        )
        object.__setattr__(
            self,
            "min_score",
            require_non_negative_float(self.min_score, "min_score"),
        )

    def to_agent_memory_query(self) -> AgentMemoryQuery:
        return AgentMemoryQuery(
            runtime_ref=self.runtime_ref,
            query=self.query,
            scope=self.scope,
            mode=self.mode,
            limit=self.max_results,
            min_score=self.min_score,
        )
