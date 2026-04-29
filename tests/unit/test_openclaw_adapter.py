import asyncio
from datetime import UTC, datetime

import pytest

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_context import AgentContextRequest, AgentRuntimeEvent
from memwing.api.agent_knowledge import (
    AgentKnowledgeExplainRequest,
    AgentKnowledgeGetRequest,
    AgentRuntimeStatusRequest,
)
from memwing.api.agent_memory import AgentMemoryQuery
from memwing.application.gateway_service import MemoryGateway
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.scope import MemoryScope, ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter


def test_openclaw_adapter_returns_empty_context_envelope() -> None:
    async def run() -> None:
        adapter, _store = _make_adapter()
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
        assert context.messages is None
        assert context.context_blocks == ()
        assert context.system_prompt_addition is None
        assert "mock" not in context.trace_id

    asyncio.run(run())


def test_openclaw_adapter_fails_memory_search_when_access_service_is_missing() -> None:
    async def run() -> None:
        adapter, _store = _make_adapter()
        runtime_ref = AgentRuntimeRef(runtime="openclaw", agent_id="main")
        scope = MemoryScope(project_memory_space_id="project_001")

        with pytest.raises(RuntimeError, match="MemoryAccessService is not configured"):
            await adapter.knowledge_search(
                AgentMemoryQuery(
                    runtime_ref=runtime_ref,
                    query="demo scope",
                    scope=scope,
                )
            )

    asyncio.run(run())


def test_openclaw_adapter_records_runtime_event_through_real_gateway_once() -> None:
    async def run() -> None:
        adapter, store = _make_adapter()
        runtime_ref = AgentRuntimeRef(
            runtime="openclaw",
            agent_id="main",
            workspace_id="workspace_001",
            session_id="session_001",
        )
        scope = MemoryScope(project_memory_space_id="project_001")
        event = AgentRuntimeEvent(
            runtime_ref=runtime_ref,
            run_id="run_001",
            message_id="message_001",
            tool_call_id=None,
            hook_name="ingest",
            sequence=1,
            idempotency_key="openclaw:main:session_001:run_001:ingest:message_001",
            event_type="message_ingested",
            scope=scope,
            content="Important event.",
            payload={"source": "openclaw"},
            event_time=datetime(2026, 4, 28, tzinfo=UTC),
        )

        first = await adapter.remember_runtime_event(event)
        second = await adapter.remember_runtime_event(event)

        assert first.accepted is True
        assert second.accepted is True
        assert second.source_event_id == first.source_event_id
        assert second.duplicate_of == first.source_event_id
        assert not first.source_event_id.startswith("mock-openclaw-source:")
        assert len(store.source_events) == 1
        assert len(store.audit_events) == 1
        assert len(store.outbox_jobs) == 4
        source_event = store.source_events[0]
        assert source_event.id == first.source_event_id
        assert source_event.runtime_event_idempotency_key == event.idempotency_key
        assert source_event.source_type == "agent_runtime.message_ingested"
        assert source_event.content == "Important event."
        assert source_event.metadata["source_ref"] == {
            "kind": "agent_runtime",
            "runtime": "openclaw",
            "agent_id": "main",
            "workspace_id": "workspace_001",
            "session_id": "session_001",
            "run_id": "run_001",
            "message_id": "message_001",
            "tool_call_id": None,
            "hook_name": "ingest",
            "event_type": "message_ingested",
        }
        assert store.audit_events[0].source_event_ids == (first.source_event_id,)
        assert {
            outbox_job.source_event_id for outbox_job in store.outbox_jobs
        } == {first.source_event_id}

    asyncio.run(run())


def test_openclaw_adapter_fails_memory_detail_access_when_service_is_missing() -> None:
    async def run() -> None:
        adapter, _store = _make_adapter()
        runtime_ref = AgentRuntimeRef(runtime="openclaw", agent_id="main")
        scope = MemoryScope(project_memory_space_id="project_001")

        with pytest.raises(RuntimeError, match="MemoryAccessService is not configured"):
            await adapter.knowledge_get(
                AgentKnowledgeGetRequest(
                    runtime_ref=runtime_ref,
                    memory_id="memory_001",
                    include_evidence=True,
                    scope=scope,
                )
            )
        with pytest.raises(RuntimeError, match="MemoryAccessService is not configured"):
            await adapter.knowledge_explain(
                AgentKnowledgeExplainRequest(
                    runtime_ref=runtime_ref,
                    memory_id="memory_001",
                    scope=scope,
                )
            )
        status = await adapter.runtime_status(AgentRuntimeStatusRequest(runtime_ref))

        assert status.healthy is False
        assert "mock" not in status.trace_id
        assert all("mock" not in capability for capability in status.capabilities)
        assert "memwing_tools_empty_envelope" not in status.capabilities
        assert "memory_access_unavailable" in status.capabilities
        assert "native_memory_shim" in status.capabilities
        assert "runtime_compaction_delegation" in status.capabilities

    asyncio.run(run())


def _make_adapter() -> tuple[OpenClawAdapter, InMemoryDataStore]:
    store = InMemoryDataStore()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Demo",
            default_safe_mode_enabled=False,
        )
    )
    store.add_runtime_scope_binding(
        RuntimeScopeBinding(
            runtime="openclaw",
            agent_id="main",
            workspace_id="workspace_001",
            session_key_pattern="session_001",
            project_memory_space_id="project_001",
        )
    )
    return OpenClawAdapter(MemoryGateway(store, ScopeResolver(store))), store
