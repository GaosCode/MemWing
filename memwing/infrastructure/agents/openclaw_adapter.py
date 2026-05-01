from __future__ import annotations

from memwing.api.agent_context import (
    AgentContextRequest,
    AgentContextResult,
    AgentRuntimeEvent,
    RememberEventResult,
)
from memwing.api.agent_knowledge import (
    AgentKnowledgeExplainRequest,
    AgentKnowledgeExplainResult,
    AgentKnowledgeGetRequest,
    AgentKnowledgeGetResult,
    AgentRuntimeStatusRequest,
    AgentRuntimeStatusResult,
)
from memwing.api.agent_memory import AgentMemoryQuery, AgentMemorySearchResult
from memwing.application.access_service import MemoryAccessService
from memwing.application.gateway_service import MemoryGateway
from memwing.application.remember_event_command import agent_runtime_event_to_remember_command


class OpenClawAdapter:
    def __init__(
        self,
        memory_gateway: MemoryGateway,
        memory_access: MemoryAccessService,
    ) -> None:
        self._memory_gateway = memory_gateway
        self._memory_access = memory_access

    async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
        return await self._memory_access.build_context(request)

    async def remember_runtime_event(self, event: AgentRuntimeEvent) -> RememberEventResult:
        command = agent_runtime_event_to_remember_command(event)
        return await self._memory_gateway.remember_event(command)

    async def knowledge_search(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        return await self._memory_access.search(query)

    async def knowledge_get(self, request: AgentKnowledgeGetRequest) -> AgentKnowledgeGetResult:
        return await self._memory_access.get(request)

    async def knowledge_explain(
        self,
        request: AgentKnowledgeExplainRequest,
    ) -> AgentKnowledgeExplainResult:
        return await self._memory_access.explain(request)

    async def runtime_status(self, request: AgentRuntimeStatusRequest) -> AgentRuntimeStatusResult:
        return AgentRuntimeStatusResult(
            runtime_ref=request.runtime_ref,
            healthy=True,
            capabilities=(
                "context_engine",
                "hook_event_mapping",
                "memory_gateway_remember_event",
                "memory_access_read_model",
                "native_memory_shim",
                "runtime_compaction_delegation",
            ),
            trace_id=_trace_id("openclaw_status", request.runtime_ref.agent_id),
        )


def _trace_id(prefix: str, agent_id: str) -> str:
    return f"{prefix}:{agent_id}"


__all__ = ("OpenClawAdapter",)
