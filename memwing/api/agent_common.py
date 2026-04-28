from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from memwing.api.validation import SchemaValidationError, require_text


AgentRuntimeName = Literal["openclaw", "future_agent"]


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
