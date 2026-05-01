from __future__ import annotations

from dataclasses import dataclass

from memwing.core.memory_access import (
    MemoryAccessMode as AgentMemoryMode,
    MemoryAccessQuery as AgentMemoryQuery,
    MemoryAccessResultItem as AgentMemoryResultItem,
    MemoryAccessResultSource as AgentMemoryResultSource,
    MemoryAccessSearchResult as AgentMemorySearchResult,
    MemoryAccessSort as SortOrder,
)
from memwing.core.runtime import AgentRuntimeRef
from memwing.core.scope import MemoryScope
from memwing.core.validation import require_non_negative_float, require_positive_int, require_text


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
            from memwing.core.validation import SchemaValidationError

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


__all__ = [
    "AgentMemoryMode",
    "AgentMemoryQuery",
    "AgentMemoryResultItem",
    "AgentMemoryResultSource",
    "AgentMemorySearchResult",
    "OpenClawNativeMemorySearchRequest",
    "SortOrder",
]
