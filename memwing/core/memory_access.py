from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from memwing.core.runtime import AgentRuntimeRef
from memwing.core.scope import MemoryScope
from memwing.core.types import JsonObject
from memwing.core.validation import (
    SchemaValidationError,
    require_non_negative_float,
    require_positive_int,
    require_text,
)


MemoryAccessSort = Literal["relevance", "event_time", "updated_at"]
MemoryAccessMode = Literal["current", "history"]
MemoryAccessResultSource = Literal[
    "graph",
    "memory_item",
    "page_memory",
    "evidence",
    "working_memory",
]


@dataclass(frozen=True, slots=True)
class MemoryAccessQuery:
    runtime_ref: AgentRuntimeRef
    query: str
    scope: MemoryScope
    mode: MemoryAccessMode = "current"
    limit: int = 20
    cursor: str | None = None
    sort: MemoryAccessSort = "relevance"
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
class MemoryAccessResultItem:
    id: str
    text: str
    score: float | None
    source: MemoryAccessResultSource
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
class MemoryAccessSearchResult:
    contexts: tuple[str, ...]
    results: tuple[MemoryAccessResultItem, ...]
    next_cursor: str | None
    trace_id: str
    warnings: tuple[dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "contexts", tuple(self.contexts))
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if self.next_cursor is not None:
            object.__setattr__(
                self,
                "next_cursor",
                require_text(self.next_cursor, "next_cursor"),
            )
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


@dataclass(frozen=True, slots=True)
class MemoryAccessGetRequest:
    runtime_ref: AgentRuntimeRef
    memory_id: str
    include_evidence: bool
    scope: MemoryScope

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", require_text(self.memory_id, "memory_id"))


@dataclass(frozen=True, slots=True)
class MemoryAccessGetResult:
    item: MemoryAccessResultItem | None
    evidence: tuple[MemoryAccessResultItem, ...]
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


@dataclass(frozen=True, slots=True)
class MemoryAccessExplainRequest:
    runtime_ref: AgentRuntimeRef
    memory_id: str
    scope: MemoryScope

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", require_text(self.memory_id, "memory_id"))


@dataclass(frozen=True, slots=True)
class MemoryAccessExplainResult:
    memory_id: str
    source_event_ids: tuple[str, ...]
    rationale: str
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", require_text(self.memory_id, "memory_id"))
        object.__setattr__(
            self,
            "source_event_ids",
            tuple(
                require_text(source_id, "source_event_ids")
                for source_id in self.source_event_ids
            ),
        )
        object.__setattr__(self, "rationale", require_text(self.rationale, "rationale"))
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))
