import asyncio
from datetime import UTC, datetime

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
from memwing.api.memwing_tools import memwing_search_memory
from memwing.api.openclaw_memory import native_memory_search, native_memory_status
from memwing.api.openclaw_runtime import (
    assemble_openclaw_context,
    complete_openclaw_turn,
    delegate_compaction_to_runtime,
    ingest_openclaw_event,
    observe_openclaw_hook,
)
from memwing.api.validation import SchemaValidationError


EVENT_TIME = datetime(2026, 4, 28, tzinfo=UTC)


def test_openclaw_context_assemble_validates_and_routes_to_runtime() -> None:
    async def run() -> None:
        runtime = RecordingRuntime()
        result = await assemble_openclaw_context(
            {
                "agent_id": "main",
                "session_id": "session_001",
                "prompt": "What is the demo scope?",
                "messages": [{"role": "user", "content": "What changed?"}],
                "token_budget": 2048,
                "available_tools": ["memwing_search_memory"],
                "scope": {"project_memory_space_id": "project_001"},
            },
            runtime,
        )

        assert result.trace_id == "trace_context"
        assert runtime.context_requests[0].runtime_ref.agent_id == "main"
        assert runtime.context_requests[0].available_tools == ("memwing_search_memory",)

    asyncio.run(run())


def test_openclaw_event_endpoints_validate_and_route() -> None:
    async def run() -> None:
        runtime = RecordingRuntime()
        ingest_result = await ingest_openclaw_event(_event_payload("ingest"), runtime)
        turn_result = await complete_openclaw_turn(_event_payload("afterTurn"), runtime)
        hook_result = await observe_openclaw_hook(
            {
                **_event_payload("after_tool_call"),
                "hook_name": "after_tool_call",
                "tool_call_id": "tool_001",
            },
            runtime,
        )

        assert ingest_result.accepted is True
        assert turn_result.accepted is True
        assert hook_result.accepted is True
        assert [event.event_type for event in runtime.events] == [
            "message_ingested",
            "turn_completed",
            "tool_call_completed",
        ]

    asyncio.run(run())


def test_memwing_search_memory_uses_empty_envelope_and_canonical_limit() -> None:
    async def run() -> None:
        runtime = RecordingRuntime()
        result = await memwing_search_memory(
            {
                "agent_id": "main",
                "query": "demo scope",
                "mode": "history",
                "limit": 7,
                "cursor": "cursor_001",
                "sort": "event_time",
                "scope": {"project_memory_space_id": "project_001"},
            },
            runtime,
        )

        assert result.contexts == ()
        assert result.results == ()
        assert runtime.queries[0].limit == 7
        assert runtime.queries[0].mode == "history"
        assert runtime.queries[0].sort == "event_time"

    asyncio.run(run())


def test_memwing_search_memory_rejects_native_max_results() -> None:
    async def run() -> None:
        runtime = RecordingRuntime()
        with pytest.raises(SchemaValidationError, match="max_results"):
            await memwing_search_memory(
                {
                    "agent_id": "main",
                    "query": "demo scope",
                    "max_results": 9,
                    "scope": {"project_memory_space_id": "project_001"},
                },
                runtime,
            )

        assert runtime.queries == []

    asyncio.run(run())


def test_native_memory_search_converts_max_results_at_boundary() -> None:
    async def run() -> None:
        runtime = RecordingRuntime()
        result = await native_memory_search(
            {
                "agent_id": "main",
                "query": "demo scope",
                "max_results": 3,
                "scope": {"project_memory_space_id": "project_001"},
            },
            runtime,
        )

        assert result["contexts"] == ()
        assert runtime.queries[0].limit == 3
        assert not hasattr(runtime.queries[0], "max_results")

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


def test_compaction_delegation_envelope_is_not_noop() -> None:
    result = delegate_compaction_to_runtime(
        {"agent_id": "main", "messages": [{"role": "user", "content": "hello"}]},
        {"strategy": "runtime", "compacted": True},
    )

    assert result["delegated"] is True
    assert result["delegate"] == "openclaw_runtime"
    assert result["result"] == {"strategy": "runtime", "compacted": True}


def test_invalid_payloads_fail_schema_validation() -> None:
    with pytest.raises(SchemaValidationError, match="agent_id"):
        asyncio.run(
            assemble_openclaw_context(
                {
                    "scope": {"project_memory_space_id": "project_001"},
                }
            )
        )

    with pytest.raises(SchemaValidationError, match="max_results"):
        asyncio.run(
            native_memory_search(
                {
                    "agent_id": "main",
                    "query": "demo scope",
                    "max_results": 0,
                    "scope": {"project_memory_space_id": "project_001"},
                }
            )
        )


def _event_payload(hook_name: str) -> dict[str, object]:
    return {
        "agent_id": "main",
        "session_id": "session_001",
        "run_id": "run_001",
        "message_id": "message_001",
        "hook_name": hook_name,
        "sequence": 1,
        "scope": {"project_memory_space_id": "project_001"},
        "content": "Event content",
        "payload": {"kind": hook_name},
        "event_time": EVENT_TIME,
    }


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
