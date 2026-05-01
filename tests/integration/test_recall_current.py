import asyncio
from datetime import UTC, datetime

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_context import AgentContextRequest
from memwing.api.agent_memory import AgentMemoryQuery
from memwing.application.access_service import MemoryAccessService
from memwing.application.current_truth import CurrentTruthModule
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.models import MemoryStatus
from memwing.core.scope import MemoryScope, ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from tests.unit.test_current_truth_module import _memory_item, _page_memory


NOW = datetime(2026, 5, 1, tzinfo=UTC)


def test_recall_current_uses_current_truth_without_sync_recall_counter_updates() -> None:
    store = InMemoryDataStore()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Project",
            default_safe_mode_enabled=False,
        )
    )
    store.add_runtime_scope_binding(
        RuntimeScopeBinding(
            runtime="openclaw",
            agent_id="agent_001",
            workspace_id=None,
            session_key_pattern="*",
            project_memory_space_id="project_001",
        )
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item("memory_active", MemoryStatus.ACTIVE))
            await tx.memory_items.upsert(_memory_item("memory_invalid", MemoryStatus.INVALID))
            await tx.memory_pages.upsert(_page_memory())

        access = MemoryAccessService(
            ScopeResolver(store),
            store,
            current_truth=CurrentTruthModule(store, now=lambda: NOW),
            now=lambda: NOW,
        )
        result = await access.search(
            AgentMemoryQuery(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                query="Skyline",
                scope=MemoryScope(
                    project_memory_space_id="project_001",
                    group_id="group_001",
                    thread_id="thread_001",
                ),
                mode="current",
                limit=10,
            )
        )
        context = await access.build_context(
            AgentContextRequest(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                scope=MemoryScope(
                    project_memory_space_id="project_001",
                    group_id="group_001",
                    thread_id="thread_001",
                ),
                prompt="Skyline",
                messages=(),
                token_budget=None,
                available_tools=(),
            )
        )

        async with store.transaction() as tx:
            active = await tx.memory_items.get("memory_active")

        assert tuple(item.id for item in result.results) == ("memory_active", "page_001")
        assert result.results[0].source == "memory_item"
        assert result.results[1].source == "page_memory"
        assert result.warnings == ()
        assert tuple(block["id"] for block in context.context_blocks) == (
            "memory_active",
            "page_001",
        )
        assert active is not None
        assert active.recall_count == 0
        assert active.last_recalled_at is None
        assert len(store.memory_recall_events) == 1
        assert store.memory_recall_events[0].memory_id == "memory_active"
        assert store.memory_recall_events[0].source == "memory_item"
        assert store.memory_recall_events[0].trace_id == "memory_access:search:agent_001"

    asyncio.run(scenario())
