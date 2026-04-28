import asyncio

import pytest

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
from memwing.api.openclaw_memory import native_memory_search, native_memory_status
from memwing.api.validation import SchemaValidationError


def test_native_memory_search_converts_max_results_at_boundary() -> None:
    async def run() -> None:
        runtime = RecordingRuntime()
        result = await native_memory_search(
            {
                "agent_id": "main",
                "query": "demo scope",
                "mode": "history",
                "max_results": 3,
                "min_score": 0.75,
                "scope": {"project_memory_space_id": "project_001"},
            },
            runtime,
        )

        assert result["contexts"] == ()
        assert runtime.queries[0].limit == 3
        assert runtime.queries[0].mode == "history"
        assert runtime.queries[0].min_score == 0.75
        assert not hasattr(runtime.queries[0], "max_results")

    asyncio.run(run())


def test_native_memory_search_rejects_unknown_fields_and_bad_types() -> None:
    async def run() -> None:
        invalid_cases = (
            {
                "agent_id": "main",
                "query": "demo scope",
                "max_results": 3,
                "unexpected": "accepted",
                "scope": {"project_memory_space_id": "project_001"},
            },
            {
                "agent_id": "main",
                "query": "demo scope",
                "mode": "unknown",
                "max_results": 3,
                "scope": {"project_memory_space_id": "project_001"},
            },
            {
                "agent_id": "main",
                "query": "demo scope",
                "max_results": 3,
                "min_score": "0.75",
                "scope": {"project_memory_space_id": "project_001"},
            },
            {
                "agent_id": "main",
                "query": "demo scope",
                "max_results": 0,
                "scope": {"project_memory_space_id": "project_001"},
            },
        )
        for payload in invalid_cases:
            runtime = RecordingRuntime()
            with pytest.raises(SchemaValidationError):
                await native_memory_search(payload, runtime)
            assert runtime.queries == []

    asyncio.run(run())


def test_native_memory_status_returns_compat_envelope() -> None:
    async def run() -> None:
        runtime = RecordingRuntime()
        status = await native_memory_status(
            {
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "project_memory_space_id": "project_001",
            },
            runtime,
        )

        assert status.agent_id == "main"
        assert status.project_memory_space_id == "project_001"
        assert status.evidence_index_status == "mock_not_connected"
        assert "native_memory_shim" in status.capabilities

    asyncio.run(run())


class RecordingRuntime:
    def __init__(self) -> None:
        self.context_requests: list[AgentContextRequest] = []
        self.events: list[AgentRuntimeEvent] = []
        self.queries: list[AgentMemoryQuery] = []

    async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
        self.context_requests.append(request)
        return AgentContextResult(
            messages=None,
            system_prompt_addition=None,
            context_blocks=(),
            estimated_tokens=None,
            trace_id="trace_context",
        )

    async def remember_runtime_event(self, event: AgentRuntimeEvent) -> RememberEventResult:
        self.events.append(event)
        return RememberEventResult(
            source_event_id=f"source:{event.idempotency_key}",
            accepted=True,
            trace_id="trace_event",
        )

    async def knowledge_search(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        self.queries.append(query)
        return AgentMemorySearchResult(
            contexts=(),
            results=(),
            next_cursor=None,
            trace_id="trace_search",
        )

    async def knowledge_get(self, request: AgentKnowledgeGetRequest) -> AgentKnowledgeGetResult:
        return AgentKnowledgeGetResult(item=None, evidence=(), trace_id="trace_get")

    async def knowledge_explain(
        self,
        request: AgentKnowledgeExplainRequest,
    ) -> AgentKnowledgeExplainResult:
        return AgentKnowledgeExplainResult(
            memory_id=request.memory_id,
            source_event_ids=(),
            rationale="No memory explanation is available in the recording runtime.",
            trace_id="trace_explain",
        )

    async def runtime_status(self, request: AgentRuntimeStatusRequest) -> AgentRuntimeStatusResult:
        return AgentRuntimeStatusResult(
            runtime_ref=request.runtime_ref,
            healthy=True,
            capabilities=("native_memory_shim",),
            trace_id="trace_status",
        )
