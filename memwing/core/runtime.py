from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from memwing.core.scope import MemoryScope
from memwing.core.types import JsonObject
from memwing.core.validation import (
    SchemaValidationError,
    require_positive_int,
    require_text,
)


AgentRuntimeName = Literal["openclaw", "future_agent"]
AgentRuntimeEventType = Literal[
    "message_ingested",
    "turn_completed",
    "tool_call_completed",
    "llm_input_observed",
    "llm_output_observed",
    "session_started",
    "session_ended",
    "compaction_started",
    "compaction_completed",
]


@dataclass(frozen=True, slots=True)
class AgentRuntimeRef:
    runtime: AgentRuntimeName
    agent_id: str
    workspace_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.runtime not in ("openclaw", "future_agent"):
            raise SchemaValidationError("runtime is not supported")
        object.__setattr__(self, "agent_id", require_text(self.agent_id, "agent_id"))
        if self.workspace_id is not None:
            object.__setattr__(
                self,
                "workspace_id",
                require_text(self.workspace_id, "workspace_id"),
            )
        if self.session_id is not None:
            object.__setattr__(self, "session_id", require_text(self.session_id, "session_id"))


@dataclass(frozen=True, slots=True)
class AgentRuntimeEvent:
    runtime_ref: AgentRuntimeRef
    run_id: str | None
    message_id: str | None
    tool_call_id: str | None
    hook_name: str
    sequence: int | None
    idempotency_key: str
    event_type: AgentRuntimeEventType
    scope: MemoryScope
    content: str | None
    payload: JsonObject
    event_time: datetime

    def __post_init__(self) -> None:
        if self.run_id is not None:
            object.__setattr__(self, "run_id", require_text(self.run_id, "run_id"))
        if self.message_id is not None:
            object.__setattr__(
                self,
                "message_id",
                require_text(self.message_id, "message_id"),
            )
        if self.tool_call_id is not None:
            object.__setattr__(
                self,
                "tool_call_id",
                require_text(self.tool_call_id, "tool_call_id"),
            )
        object.__setattr__(self, "hook_name", require_text(self.hook_name, "hook_name"))
        if self.sequence is not None and (not isinstance(self.sequence, int) or self.sequence < 0):
            raise SchemaValidationError("sequence must be a non-negative integer")
        object.__setattr__(
            self,
            "idempotency_key",
            require_text(self.idempotency_key, "idempotency_key"),
        )
        if self.event_type not in (
            "message_ingested",
            "turn_completed",
            "tool_call_completed",
            "llm_input_observed",
            "llm_output_observed",
            "session_started",
            "session_ended",
            "compaction_started",
            "compaction_completed",
        ):
            raise SchemaValidationError("event_type is not supported")
        if self.content is not None:
            object.__setattr__(self, "content", require_text(self.content, "content"))


@dataclass(frozen=True, slots=True)
class AgentContextRequest:
    runtime_ref: AgentRuntimeRef
    scope: MemoryScope
    prompt: str | None
    messages: tuple[JsonObject, ...]
    token_budget: int | None
    available_tools: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.prompt is not None:
            object.__setattr__(self, "prompt", require_text(self.prompt, "prompt"))
        object.__setattr__(self, "messages", tuple(self.messages))
        if self.token_budget is not None:
            object.__setattr__(
                self,
                "token_budget",
                require_positive_int(self.token_budget, "token_budget"),
            )
        object.__setattr__(
            self,
            "available_tools",
            tuple(require_text(tool, "available_tools") for tool in self.available_tools),
        )


@dataclass(frozen=True, slots=True)
class AgentContextResult:
    messages: tuple[JsonObject, ...] | None
    system_prompt_addition: str | None
    context_blocks: tuple[JsonObject, ...]
    estimated_tokens: int | None
    trace_id: str

    def __post_init__(self) -> None:
        if self.messages is not None:
            object.__setattr__(self, "messages", tuple(self.messages))
        if self.system_prompt_addition is not None:
            object.__setattr__(
                self,
                "system_prompt_addition",
                require_text(self.system_prompt_addition, "system_prompt_addition"),
            )
        object.__setattr__(self, "context_blocks", tuple(self.context_blocks))
        if self.estimated_tokens is not None:
            object.__setattr__(
                self,
                "estimated_tokens",
                require_positive_int(self.estimated_tokens, "estimated_tokens"),
            )
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


@dataclass(frozen=True, slots=True)
class RememberEventResult:
    source_event_id: str
    accepted: bool
    trace_id: str
    duplicate_of: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_event_id",
            require_text(self.source_event_id, "source_event_id"),
        )
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))
        if self.duplicate_of is not None:
            object.__setattr__(
                self,
                "duplicate_of",
                require_text(self.duplicate_of, "duplicate_of"),
            )


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
