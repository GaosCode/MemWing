import asyncio
from datetime import UTC, datetime

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_context import AgentContextRequest
from memwing.api.agent_knowledge import AgentKnowledgeExplainRequest
from memwing.api.agent_memory import AgentMemoryQuery
from memwing.application.access_service import MemoryAccessService
from memwing.application.current_truth import CurrentTruthModule
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult, MemorySearchResultItem
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.models import MemoryGraphLink, MemoryStatus
from memwing.core.scope import MemoryScope, ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from tests.unit.test_current_truth_module import _memory_item, _page_memory
from tests.unit.test_current_truth_module import _source_event as raw_source_event


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


def test_recall_current_falls_back_to_raw_events_when_no_derived_memory_exists() -> None:
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
            await tx.source_events.insert_if_absent(raw_source_event())

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

        assert tuple(item.id for item in result.results) == ("source_001",)
        assert result.results[0].source == "source_event"
        assert result.results[0].metadata["source"] == "source_event"

    asyncio.run(scenario())


def test_recall_current_paginates_assembled_results_with_server_cursor() -> None:
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
            await tx.memory_items.upsert(_memory_item("memory_001", MemoryStatus.ACTIVE))
            await tx.memory_items.upsert(_memory_item("memory_002", MemoryStatus.ACTIVE))
            await tx.memory_items.upsert(_memory_item("memory_003", MemoryStatus.ACTIVE))

        access = MemoryAccessService(
            ScopeResolver(store),
            store,
            current_truth=CurrentTruthModule(store, now=lambda: NOW),
            now=lambda: NOW,
        )
        first_page = await access.search(
            AgentMemoryQuery(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                query="Skyline",
                scope=MemoryScope(
                    project_memory_space_id="project_001",
                    group_id="group_001",
                    thread_id="thread_001",
                ),
                mode="current",
                limit=2,
            )
        )
        second_page = await access.search(
            AgentMemoryQuery(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                query="Skyline",
                scope=MemoryScope(
                    project_memory_space_id="project_001",
                    group_id="group_001",
                    thread_id="thread_001",
                ),
                mode="current",
                limit=2,
                cursor=first_page.next_cursor,
            )
        )

        assert tuple(item.id for item in first_page.results) == ("memory_003", "memory_002")
        assert first_page.next_cursor == "offset:2"
        assert tuple(item.id for item in second_page.results) == ("memory_001",)
        assert second_page.next_cursor is None

    asyncio.run(scenario())


def test_recall_history_uses_graph_history_and_preserves_historical_validity() -> None:
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
    graph_backend = HistoryGraphBackend()

    async def scenario() -> None:
        access = MemoryAccessService(
            ScopeResolver(store),
            store,
            graph_backend=graph_backend,
            now=lambda: NOW,
        )
        result = await access.search(
            AgentMemoryQuery(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                query="Apollo",
                scope=MemoryScope(project_memory_space_id="project_001"),
                mode="history",
                limit=10,
            )
        )

        assert len(graph_backend.history_queries) == 1
        assert graph_backend.history_queries[0].mode == "history"
        assert tuple(item.id for item in result.results) == ("graph_fact_old",)
        assert result.results[0].source == "graph_backend"
        assert result.results[0].valid_to == NOW
        assert result.results[0].metadata["historical_state"] == "invalidated"

    asyncio.run(scenario())


def test_explain_uses_scoped_sources_and_graph_links_for_traceability() -> None:
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
            await tx.source_events.insert_if_absent(raw_source_event())
            await tx.memory_items.upsert(_memory_item("memory_active", MemoryStatus.ACTIVE))
            await tx.memory_graph_links.upsert(
                MemoryGraphLink(
                    id="link_001",
                    backend="graphiti",
                    memory_id="memory_active",
                    source_event_id="source_001",
                    project_memory_space_id="project_001",
                    backend_space_id="project_001",
                    backend_object_type="entity_edge",
                    backend_object_id="edge_001",
                    link_type="fact",
                    created_at=NOW,
                )
            )

        access = MemoryAccessService(ScopeResolver(store), store, now=lambda: NOW)
        result = await access.explain(
            AgentKnowledgeExplainRequest(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                memory_id="memory_active",
                scope=MemoryScope(project_memory_space_id="project_001"),
            )
        )

        assert result.source_event_ids == ("source_001",)
        assert "source_events=1" in result.rationale
        assert "graph_links=1" in result.rationale
        assert "graph_backend_raw_retained=true" in result.rationale

    asyncio.run(scenario())


class HistoryGraphBackend:
    def __init__(self) -> None:
        self.history_queries: list[MemorySearchQuery] = []

    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        raise AssertionError("history recall must not call search_current")

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        self.history_queries.append(query)
        item = MemorySearchResultItem(
            id="graph_fact_old",
            text="The project codename was Apollo.",
            score=0.8,
            source="graph_backend",
            source_event_ids=("source_old",),
            memory_item_ids=("memory_old",),
            valid_from=NOW,
            valid_to=NOW,
            metadata={"historical_state": "invalidated"},
        )
        return MemorySearchResult(
            contexts=(item.text,),
            results=(item,),
            next_cursor=None,
            trace_id="graph_history",
        )

    async def ingest_graph_job(self, request: object) -> object:
        raise NotImplementedError

    async def mark_source_redacted(self, source_event_id: str, scope: object) -> None:
        raise NotImplementedError
