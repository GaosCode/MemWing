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
from memwing.core.scope import EffectiveScope, MemoryScope, ProjectMemorySpace, RuntimeScopeBinding
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
        assert result.diagnostics is not None
        branch_timings = result.diagnostics["current_truth"]["branch_timings"]
        assert {timing["branch"] for timing in branch_timings} == {
            "graph_backend",
            "evidence_index",
            "working_memory",
            "memory_items",
            "page_memory",
            "raw_events",
        }
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


def test_recall_current_relevance_search_promotes_scored_evidence_over_unscored_graph() -> None:
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
        access = MemoryAccessService(
            ScopeResolver(store),
            store,
            graph_backend=UnscoredCurrentGraphBackend(),
            evidence_index=ScoredEvidenceIndex(),
            now=lambda: NOW,
        )
        result = await access.search(
            AgentMemoryQuery(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                query="岚桥质检平台长期有效的验收标准是什么？",
                scope=MemoryScope(project_memory_space_id="project_001"),
                mode="current",
                limit=2,
                sort="relevance",
            )
        )

        assert tuple(item.id for item in result.results) == ("evidence_fact", "graph_fact")
        assert result.results[0].source == "evidence_index"
        assert result.results[1].source == "graph_backend"

    asyncio.run(scenario())


def test_recall_current_relevance_search_uses_query_terms_to_break_close_vector_scores() -> None:
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
        access = MemoryAccessService(
            ScopeResolver(store),
            store,
            evidence_index=CloseScoreEvidenceIndex(),
            now=lambda: NOW,
        )
        result = await access.search(
            AgentMemoryQuery(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                query="云帆看板改造项目现在的负责人是谁？",
                scope=MemoryScope(project_memory_space_id="project_001"),
                mode="current",
                limit=2,
                sort="relevance",
            )
        )

        assert tuple(item.id for item in result.results) == ("owner_fact", "acceptance_fact")

    asyncio.run(scenario())


def test_recall_current_relevance_search_adds_assembled_context_for_compound_questions() -> None:
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
        access = MemoryAccessService(
            ScopeResolver(store),
            store,
            evidence_index=CompoundEvidenceIndex(),
            now=lambda: NOW,
        )
        result = await access.search(
            AgentMemoryQuery(
                runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_001"),
                query="海棠账单和海棠结算的上线窗口分别是什么？不要混淆。",
                scope=MemoryScope(project_memory_space_id="project_001"),
                mode="current",
                limit=3,
                sort="relevance",
            )
        )

        assert result.results[0].id == "current_truth:assembled"
        assert result.results[0].source == "working_memory"
        assert "海棠账单的上线窗口是 2026-05-06 20:00-22:00" in result.results[0].text
        assert "海棠结算的上线窗口是 2026-05-07 01:00-03:00" in result.results[0].text
        assert {item.id for item in result.results[1:]} == {"bill_window", "settlement_window"}

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


class UnscoredCurrentGraphBackend:
    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        item = MemorySearchResultItem(
            id="graph_fact",
            text="知识库旧链接暂时可正常访问。",
            score=None,
            source="graph_backend",
            source_event_ids=("source_graph",),
            memory_item_ids=(),
            valid_from=NOW,
            valid_to=None,
            metadata={},
        )
        return MemorySearchResult(
            contexts=(item.text,),
            results=(item,),
            next_cursor=None,
            trace_id="graph_current",
        )

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: object) -> object:
        raise NotImplementedError

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class ScoredEvidenceIndex:
    async def index_source_event(self, source_event: object, scope: EffectiveScope) -> None:
        raise NotImplementedError

    async def search(self, query: MemorySearchQuery) -> MemorySearchResult:
        item = MemorySearchResultItem(
            id="evidence_fact",
            text="岚桥质检平台的长期有效验收阈值为抽检通过率不低于 98%，P95 响应时间不高于 800ms。",
            score=0.92,
            source="evidence_index",
            source_event_ids=("source_evidence",),
            memory_item_ids=(),
            valid_from=None,
            valid_to=None,
            metadata={},
        )
        return MemorySearchResult(
            contexts=(item.text,),
            results=(item,),
            next_cursor=None,
            trace_id="evidence_current",
        )

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class CloseScoreEvidenceIndex:
    async def index_source_event(self, source_event: object, scope: EffectiveScope) -> None:
        raise NotImplementedError

    async def search(self, query: MemorySearchQuery) -> MemorySearchResult:
        items = (
            MemorySearchResultItem(
                id="acceptance_fact",
                text="云帆看板改造的验收人是韩悦，最终验收截止时间为 2026-04-30 18:00。",
                score=0.83,
                source="evidence_index",
                source_event_ids=("source_acceptance",),
                memory_item_ids=(),
                valid_from=None,
                valid_to=None,
                metadata={},
            ),
            MemorySearchResultItem(
                id="owner_fact",
                text="项目晨会结论：云帆看板改造项目负责人确定为沈南，负责需求收口和跨部门协调。",
                score=0.82,
                source="evidence_index",
                source_event_ids=("source_owner",),
                memory_item_ids=(),
                valid_from=None,
                valid_to=None,
                metadata={},
            ),
        )
        return MemorySearchResult(
            contexts=tuple(item.text for item in items),
            results=items,
            next_cursor=None,
            trace_id="evidence_current",
        )

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class CompoundEvidenceIndex:
    async def index_source_event(self, source_event: object, scope: EffectiveScope) -> None:
        raise NotImplementedError

    async def search(self, query: MemorySearchQuery) -> MemorySearchResult:
        items = (
            MemorySearchResultItem(
                id="bill_window",
                text="海棠账单的上线窗口是 2026-05-06 20:00-22:00，当前负责人是秦榆。",
                score=0.88,
                source="evidence_index",
                source_event_ids=("source_bill",),
                memory_item_ids=(),
                valid_from=None,
                valid_to=None,
                metadata={},
            ),
            MemorySearchResultItem(
                id="settlement_window",
                text="海棠结算的上线窗口是 2026-05-07 01:00-03:00，当前负责人是孟棠。",
                score=0.87,
                source="evidence_index",
                source_event_ids=("source_settlement",),
                memory_item_ids=(),
                valid_from=None,
                valid_to=None,
                metadata={},
            ),
        )
        return MemorySearchResult(
            contexts=tuple(item.text for item in items),
            results=items,
            next_cursor=None,
            trace_id="evidence_current",
        )

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError
