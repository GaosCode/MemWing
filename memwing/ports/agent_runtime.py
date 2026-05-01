from __future__ import annotations

from typing import Protocol, runtime_checkable

from memwing.core.memory_access import (
    MemoryAccessExplainRequest,
    MemoryAccessExplainResult,
    MemoryAccessGetRequest,
    MemoryAccessGetResult,
    MemoryAccessQuery,
    MemoryAccessSearchResult,
)
from memwing.core.runtime import (
    AgentContextRequest,
    AgentContextResult,
    AgentRuntimeEvent,
    AgentRuntimeStatusRequest,
    AgentRuntimeStatusResult,
    RememberEventResult,
)


@runtime_checkable
class AgentRuntimePort(Protocol):
    async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
        ...

    async def remember_runtime_event(self, event: AgentRuntimeEvent) -> RememberEventResult:
        ...

    async def knowledge_search(self, query: MemoryAccessQuery) -> MemoryAccessSearchResult:
        ...

    async def knowledge_get(self, request: MemoryAccessGetRequest) -> MemoryAccessGetResult:
        ...

    async def knowledge_explain(
        self, request: MemoryAccessExplainRequest
    ) -> MemoryAccessExplainResult:
        ...

    async def runtime_status(self, request: AgentRuntimeStatusRequest) -> AgentRuntimeStatusResult:
        ...
