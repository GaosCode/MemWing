import asyncio
from datetime import UTC, datetime

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_context import AgentContextRequest, AgentRuntimeEvent
from memwing.api.agent_knowledge import (
    AgentKnowledgeExplainRequest,
    AgentKnowledgeGetRequest,
    AgentRuntimeStatusRequest,
)
from memwing.api.agent_memory import AgentMemoryQuery
from memwing.core.scope import MemoryScope
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter


def test_openclaw_adapter_returns_empty_context_and_search_envelopes() -> None:
    async def run() -> None:
        adapter = OpenClawAdapter()
        runtime_ref = AgentRuntimeRef(runtime="openclaw", agent_id="main")
        scope = MemoryScope(project_memory_space_id="project_001")

        context = await adapter.build_context(
            AgentContextRequest(
                runtime_ref=runtime_ref,
                scope=scope,
                prompt="What matters?",
                messages=(),
                token_budget=1024,
                available_tools=("memwing_search_memory",),
            )
        )
        search = await adapter.knowledge_search(
            AgentMemoryQuery(
                runtime_ref=runtime_ref,
                query="demo scope",
                scope=scope,
            )
        )

        assert context.messages is None
        assert context.context_blocks == ()
        assert context.system_prompt_addition is None
        assert search.contexts == ()
        assert search.results == ()
        assert search.next_cursor is None

    asyncio.run(run())


def test_openclaw_adapter_records_runtime_event_as_mock_source_event() -> None:
    async def run() -> None:
        adapter = OpenClawAdapter()
        runtime_ref = AgentRuntimeRef(runtime="openclaw", agent_id="main")
        scope = MemoryScope(project_memory_space_id="project_001")
        result = await adapter.remember_runtime_event(
            AgentRuntimeEvent(
                runtime_ref=runtime_ref,
                run_id="run_001",
                message_id="message_001",
                tool_call_id=None,
                hook_name="ingest",
                sequence=1,
                idempotency_key="openclaw:main:session:run_001:ingest:message_001",
                event_type="message_ingested",
                scope=scope,
                content="Important event.",
                payload={},
                event_time=datetime(2026, 4, 28, tzinfo=UTC),
            )
        )

        assert result.accepted is True
        assert result.source_event_id.startswith("mock-openclaw-source:")

    asyncio.run(run())


def test_openclaw_adapter_get_explain_and_status_are_mock_boundaries() -> None:
    async def run() -> None:
        adapter = OpenClawAdapter()
        runtime_ref = AgentRuntimeRef(runtime="openclaw", agent_id="main")
        scope = MemoryScope(project_memory_space_id="project_001")

        get_result = await adapter.knowledge_get(
            AgentKnowledgeGetRequest(
                runtime_ref=runtime_ref,
                memory_id="memory_001",
                include_evidence=True,
                scope=scope,
            )
        )
        explain_result = await adapter.knowledge_explain(
            AgentKnowledgeExplainRequest(
                runtime_ref=runtime_ref,
                memory_id="memory_001",
                scope=scope,
            )
        )
        status = await adapter.runtime_status(AgentRuntimeStatusRequest(runtime_ref))

        assert get_result.item is None
        assert get_result.evidence == ()
        assert explain_result.source_event_ids == ()
        assert "native_memory_shim" in status.capabilities
        assert "runtime_compaction_delegation" in status.capabilities

    asyncio.run(run())
