from __future__ import annotations

from memwing.api.agent_context import AgentContextRequest, AgentContextResult
from memwing.api.agent_knowledge import (
    AgentKnowledgeExplainRequest,
    AgentKnowledgeExplainResult,
    AgentKnowledgeGetRequest,
    AgentKnowledgeGetResult,
)
from memwing.api.agent_memory import AgentMemoryQuery, AgentMemorySearchResult
from memwing.application.scope_resolver import ScopeResolver


class MemoryAccessService:
    def __init__(self, scope_resolver: ScopeResolver) -> None:
        self._scope_resolver = scope_resolver

    async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
        await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        return AgentContextResult(
            messages=None,
            system_prompt_addition=None,
            context_blocks=(),
            estimated_tokens=None,
            trace_id=_trace_id("context", request.runtime_ref.agent_id),
        )

    async def search(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        await self._scope_resolver.resolve_runtime(query.runtime_ref, query.scope)
        return AgentMemorySearchResult(
            contexts=(),
            results=(),
            next_cursor=None,
            trace_id=_trace_id("search", query.runtime_ref.agent_id),
        )

    async def get(self, request: AgentKnowledgeGetRequest) -> AgentKnowledgeGetResult:
        await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        return AgentKnowledgeGetResult(
            item=None,
            evidence=(),
            trace_id=_trace_id("get", request.runtime_ref.agent_id),
        )

    async def explain(self, request: AgentKnowledgeExplainRequest) -> AgentKnowledgeExplainResult:
        await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        return AgentKnowledgeExplainResult(
            memory_id=request.memory_id,
            source_event_ids=(),
            rationale="No indexed memory record is available for this id.",
            trace_id=_trace_id("explain", request.runtime_ref.agent_id),
        )


def _trace_id(operation: str, agent_id: str) -> str:
    return f"memory_access:{operation}:{agent_id}"
