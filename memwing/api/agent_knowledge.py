from __future__ import annotations

from dataclasses import dataclass

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_memory import AgentMemoryResultItem
from memwing.api.validation import require_text
from memwing.core.scope import MemoryScope


@dataclass(frozen=True, slots=True)
class AgentKnowledgeGetRequest:
    runtime_ref: AgentRuntimeRef
    memory_id: str
    include_evidence: bool
    scope: MemoryScope

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", require_text(self.memory_id, "memory_id"))


@dataclass(frozen=True, slots=True)
class AgentKnowledgeGetResult:
    item: AgentMemoryResultItem | None
    evidence: tuple[AgentMemoryResultItem, ...]
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


@dataclass(frozen=True, slots=True)
class AgentKnowledgeExplainRequest:
    runtime_ref: AgentRuntimeRef
    memory_id: str
    scope: MemoryScope

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", require_text(self.memory_id, "memory_id"))


@dataclass(frozen=True, slots=True)
class AgentKnowledgeExplainResult:
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


@dataclass(frozen=True, slots=True)
class AgentRuntimeStatusRequest:
    runtime_ref: AgentRuntimeRef


@dataclass(frozen=True, slots=True)
class AgentRuntimeStatusResult:
    runtime_ref: AgentRuntimeRef
    healthy: bool
    capabilities: tuple[str, ...]
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capabilities",
            tuple(require_text(capability, "capabilities") for capability in self.capabilities),
        )
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))
