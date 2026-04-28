from __future__ import annotations

from typing import Protocol, runtime_checkable

from memwing.api.agent_runtime import (
    AgentContextRequest,
    AgentContextResult,
    AgentKnowledgeExplainRequest,
    AgentKnowledgeExplainResult,
    AgentKnowledgeGetRequest,
    AgentKnowledgeGetResult,
    AgentMemoryQuery,
    AgentMemorySearchResult,
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

    async def knowledge_search(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        ...

    async def knowledge_get(self, request: AgentKnowledgeGetRequest) -> AgentKnowledgeGetResult:
        ...

    async def knowledge_explain(
        self, request: AgentKnowledgeExplainRequest
    ) -> AgentKnowledgeExplainResult:
        ...

    async def runtime_status(self, request: AgentRuntimeStatusRequest) -> AgentRuntimeStatusResult:
        ...
