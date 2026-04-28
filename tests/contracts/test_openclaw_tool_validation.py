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
from memwing.api.memwing_tools import (
    memwing_explain_memory,
    memwing_get_memory,
    memwing_get_project_context,
    memwing_search_memory,
    memwing_search_sources,
)
from memwing.api.validation import SchemaValidationError


def test_memwing_tools_reject_unknown_top_level_fields_before_runtime() -> None:
    async def run() -> None:
        invalid_cases = (
            (
                memwing_search_memory,
                {
                    "agent_id": "main",
                    "query": "demo scope",
                    "max_results": 9,
                    "scope": {"project_memory_space_id": "project_001"},
                },
                "max_results",
            ),
            (
                memwing_get_memory,
                {
                    "agent_id": "main",
                    "memory_id": "memory_001",
                    "unexpected": "accepted",
                    "scope": {"project_memory_space_id": "project_001"},
                },
                "unexpected",
            ),
            (
                memwing_explain_memory,
                {
                    "agent_id": "main",
                    "memory_id": "memory_001",
                    "max_results": 9,
                    "scope": {"project_memory_space_id": "project_001"},
                },
                "max_results",
            ),
            (
                memwing_search_sources,
                {
                    "agent_id": "main",
                    "query": "demo scope",
                    "unexpected": "accepted",
                    "scope": {"project_memory_space_id": "project_001"},
                },
                "unexpected",
            ),
            (
                memwing_get_project_context,
                {
                    "agent_id": "main",
                    "max_results": 9,
                    "scope": {"project_memory_space_id": "project_001"},
                },
                "max_results",
            ),
        )

        for tool, payload, expected_error in invalid_cases:
            runtime = RecordingRuntime()
            with pytest.raises(SchemaValidationError, match=expected_error):
                await tool(payload, runtime)
            assert_runtime_unused(runtime)

    asyncio.run(run())


def assert_runtime_unused(runtime: "RecordingRuntime") -> None:
    assert runtime.context_requests == []
    assert runtime.events == []
    assert runtime.queries == []
    assert runtime.get_requests == []
    assert runtime.explain_requests == []


class RecordingRuntime:
    def __init__(self) -> None:
        self.context_requests: list[AgentContextRequest] = []
        self.events: list[AgentRuntimeEvent] = []
        self.queries: list[AgentMemoryQuery] = []
        self.get_requests: list[AgentKnowledgeGetRequest] = []
        self.explain_requests: list[AgentKnowledgeExplainRequest] = []

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
        self.get_requests.append(request)
        return AgentKnowledgeGetResult(item=None, evidence=(), trace_id="trace_get")

    async def knowledge_explain(
        self,
        request: AgentKnowledgeExplainRequest,
    ) -> AgentKnowledgeExplainResult:
        self.explain_requests.append(request)
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
