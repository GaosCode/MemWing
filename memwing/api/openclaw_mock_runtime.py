from __future__ import annotations

from memwing.api.agent_context import AgentContextRequest, AgentContextResult, AgentRuntimeEvent, RememberEventResult
from memwing.api.agent_knowledge import (
    AgentKnowledgeExplainRequest,
    AgentKnowledgeExplainResult,
    AgentKnowledgeGetRequest,
    AgentKnowledgeGetResult,
    AgentRuntimeStatusRequest,
    AgentRuntimeStatusResult,
)
from memwing.api.agent_memory import AgentMemoryQuery, AgentMemorySearchResult


class OpenClawMockRuntime:
    async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
        return AgentContextResult(
            messages=None,
            system_prompt_addition=None,
            context_blocks=(),
            estimated_tokens=None,
            trace_id=_trace_id("openclaw_context", request.runtime_ref.agent_id),
        )

    async def remember_runtime_event(self, event: AgentRuntimeEvent) -> RememberEventResult:
        return RememberEventResult(
            source_event_id=f"mock-openclaw-source:{event.idempotency_key}",
            accepted=True,
            trace_id=_trace_id("openclaw_event", event.runtime_ref.agent_id),
        )

    async def knowledge_search(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        return AgentMemorySearchResult(
            contexts=(),
            results=(),
            next_cursor=None,
            trace_id=_trace_id("openclaw_search", query.runtime_ref.agent_id),
        )

    async def knowledge_get(self, request: AgentKnowledgeGetRequest) -> AgentKnowledgeGetResult:
        return AgentKnowledgeGetResult(
            item=None,
            evidence=(),
            trace_id=_trace_id("openclaw_get", request.runtime_ref.agent_id),
        )

    async def knowledge_explain(
        self,
        request: AgentKnowledgeExplainRequest,
    ) -> AgentKnowledgeExplainResult:
        return AgentKnowledgeExplainResult(
            memory_id=request.memory_id,
            source_event_ids=(),
            rationale="No memory explanation is available in the OpenClaw mock adapter.",
            trace_id=_trace_id("openclaw_explain", request.runtime_ref.agent_id),
        )

    async def runtime_status(self, request: AgentRuntimeStatusRequest) -> AgentRuntimeStatusResult:
        return AgentRuntimeStatusResult(
            runtime_ref=request.runtime_ref,
            healthy=True,
            capabilities=(
                "context_engine",
                "hook_event_mapping",
                "memwing_tools_empty_envelope",
                "native_memory_shim",
                "runtime_compaction_delegation",
            ),
            trace_id=_trace_id("openclaw_status", request.runtime_ref.agent_id),
        )


def _trace_id(prefix: str, agent_id: str) -> str:
    return f"{prefix}:{agent_id}:mock"
