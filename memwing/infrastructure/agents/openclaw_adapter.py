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
from memwing.application.gateway_service import MemoryGateway
from memwing.application.remember_event_command import agent_runtime_event_to_remember_command


class OpenClawAdapter:
    def __init__(self, memory_gateway: MemoryGateway) -> None:
        self._memory_gateway = memory_gateway

    async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
        return AgentContextResult(
            messages=None,
            system_prompt_addition=None,
            context_blocks=(),
            estimated_tokens=None,
            trace_id=_trace_id("openclaw_context", request.runtime_ref.agent_id),
        )

    async def remember_runtime_event(self, event: AgentRuntimeEvent) -> RememberEventResult:
        command = agent_runtime_event_to_remember_command(event)
        return await self._memory_gateway.remember_event(command)

    async def knowledge_search(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise _memory_access_unavailable()

    async def knowledge_get(self, request: AgentKnowledgeGetRequest) -> AgentKnowledgeGetResult:
        raise _memory_access_unavailable()

    async def knowledge_explain(
        self,
        request: AgentKnowledgeExplainRequest,
    ) -> AgentKnowledgeExplainResult:
        raise _memory_access_unavailable()

    async def runtime_status(self, request: AgentRuntimeStatusRequest) -> AgentRuntimeStatusResult:
        return AgentRuntimeStatusResult(
            runtime_ref=request.runtime_ref,
            healthy=False,
            capabilities=(
                "context_engine",
                "hook_event_mapping",
                "memory_gateway_remember_event",
                "memory_access_unavailable",
                "native_memory_shim",
                "runtime_compaction_delegation",
            ),
            trace_id=_trace_id("openclaw_status", request.runtime_ref.agent_id),
        )


def _trace_id(prefix: str, agent_id: str) -> str:
    return f"{prefix}:{agent_id}:memory_access_unavailable"


def _memory_access_unavailable() -> RuntimeError:
    return RuntimeError("MemoryAccessService is not configured")


__all__ = ("OpenClawAdapter",)
