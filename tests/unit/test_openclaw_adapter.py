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
from memwing.application.access_service import MemoryAccessService
from memwing.application.gateway_service import MemoryGateway
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.models import MemoryDisplayType, MemoryItem, MemoryRoute, MemoryStatus, SourceEvent
from memwing.core.scope import MemoryScope, ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter


def test_openclaw_adapter_returns_empty_context_envelope() -> None:
    async def run() -> None:
        adapter, store = _make_adapter()
        await _seed_memory(store)
        runtime_ref = _bound_runtime_ref()
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


def test_openclaw_adapter_routes_memory_search_through_access_service() -> None:
    async def run() -> None:
        adapter, store = _make_adapter()
        await _seed_memory(store)
        runtime_ref = _bound_runtime_ref()
        scope = MemoryScope(project_memory_space_id="project_001")

        result = await adapter.knowledge_search(
            AgentMemoryQuery(
                runtime_ref=runtime_ref,
                query="demo scope",
                scope=scope,
            )
        )

        assert tuple(item.id for item in result.results) == ("memory_001",)
        assert result.contexts == ("Demo scope remains Feishu plus OpenClaw.",)
        assert result.trace_id == "memory_access:search:main"

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


def test_openclaw_adapter_routes_memory_detail_access_through_access_service() -> None:
    async def run() -> None:
        adapter, store = _make_adapter()
        await _seed_memory(store)
        runtime_ref = _bound_runtime_ref()
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

        assert get_result.item is not None
        assert get_result.item.id == "memory_001"
        assert tuple(item.id for item in get_result.evidence) == ("source_001",)
        assert explain_result.memory_id == "memory_001"
        assert explain_result.source_event_ids == ("source_001",)
        assert status.healthy is True
        assert "mock" not in status.trace_id
        assert all("mock" not in capability for capability in status.capabilities)
        assert "memwing_tools_empty_envelope" not in status.capabilities
        assert "memory_access_read_model" in status.capabilities
        assert "memory_access_unavailable" not in status.capabilities
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
    resolver = ScopeResolver(store)
    return OpenClawAdapter(MemoryGateway(store, resolver), MemoryAccessService(resolver, store)), store


def _bound_runtime_ref() -> AgentRuntimeRef:
    return AgentRuntimeRef(
        runtime="openclaw",
        agent_id="main",
        workspace_id="workspace_001",
        session_id="session_001",
    )


async def _seed_memory(store: InMemoryDataStore) -> None:
    async with store.transaction() as tx:
        await tx.source_events.insert_if_absent(
            SourceEvent(
                id="source_001",
                project_memory_space_id="project_001",
                group_id=None,
                thread_id=None,
                shared_group_id=None,
                author_id="user_001",
                author_name="Ada",
                source_type="agent_runtime.message_ingested",
                content="Demo scope remains Feishu plus OpenClaw.",
                content_preview="Demo scope remains Feishu plus OpenClaw.",
                source_url=None,
                event_time=datetime(2026, 4, 28, tzinfo=UTC),
                raw_payload_hash="hash_001",
                metadata={},
                purged_at=None,
                purged_by=None,
                purge_reason=None,
                purge_level="none",
                graph_backend_raw_retained=False,
                created_at=datetime(2026, 4, 28, tzinfo=UTC),
                runtime_event_idempotency_key="runtime:source_001",
            )
        )
        await tx.memory_items.upsert(
            MemoryItem(
                id="memory_001",
                project_memory_space_id="project_001",
                group_id=None,
                thread_id=None,
                shared_group_id=None,
                route=MemoryRoute.VECTOR_ONLY,
                display_type=MemoryDisplayType.NOTE,
                title="Demo scope",
                content="Demo scope remains Feishu plus OpenClaw.",
                summary=None,
                source_event_ids=("source_001",),
                primary_source_event_id="source_001",
                status=MemoryStatus.ACTIVE,
                event_time=datetime(2026, 4, 28, tzinfo=UTC),
                valid_from=None,
                valid_to=None,
                original_score=0.9,
                half_life_days=30,
                last_reviewed_at=None,
                last_confirmed_at=None,
                last_recalled_at=None,
                recall_count=0,
                cached_decayed_score=0.9,
                last_decay_computed_at=datetime(2026, 4, 28, tzinfo=UTC),
                pinned=False,
                created_by="system",
                created_at=datetime(2026, 4, 28, tzinfo=UTC),
                activated_at=datetime(2026, 4, 28, tzinfo=UTC),
                updated_at=datetime(2026, 4, 28, tzinfo=UTC),
                archived_at=None,
                hidden_at=None,
                invalidated_at=None,
                removed_at=None,
            )
        )
