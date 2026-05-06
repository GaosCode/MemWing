import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.application.current_truth import CurrentTruthModule
from memwing.application.memory_access_read_model import current_truth_to_access_result
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult, MemorySearchResultItem
from memwing.core.models import (
    MemoryGraphLink,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    PageMemory,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore


NOW = datetime(2026, 5, 1, tzinfo=UTC)


def test_current_truth_returns_active_memory_and_downgrades_page_memory_to_background() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item("memory_active", MemoryStatus.ACTIVE))
            await tx.memory_items.upsert(_memory_item("memory_invalid", MemoryStatus.INVALID))
            await tx.memory_pages.upsert(_page_memory())

        result = await CurrentTruthModule(store, now=lambda: NOW).recall_current(
            MemorySearchQuery(
                query="Skyline",
                scope=_scope(),
                limit=10,
                trace_id="trace_current",
            )
        )

        assert tuple(item.id for item in result.current_facts) == ("memory_active",)
        assert result.current_facts[0].source == "memory_item"
        assert tuple(item.id for item in result.background) == ("page_001",)
        assert result.background[0].source == "page_memory"
        assert result.supporting_evidence == ()
        assert result.warnings == ()
        assert {
            timing.branch: timing.result_count for timing in result.branch_timings
        } == {
            "graph_backend": 0,
            "evidence_index": 0,
            "working_memory": 0,
            "memory_items": 1,
            "page_memory": 1,
            "raw_events": 0,
        }
        assert result.trace_id == "trace_current"

    asyncio.run(scenario())


def test_current_truth_uses_relevance_for_memory_items_and_ranks_deadline_context() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(
                replace(
                    _memory_item("memory_deadline", MemoryStatus.ACTIVE),
                    title="云帆看板改造最终验收截止时间",
                    content="云帆看板改造的最终验收截止时间是 2026-04-30 18:00。",
                    source_event_ids=("source_deadline",),
                    primary_source_event_id="source_deadline",
                )
            )
            await tx.memory_items.upsert(
                replace(
                    _memory_item("memory_owner", MemoryStatus.ACTIVE),
                    title="云帆看板改造负责人",
                    content="云帆看板改造项目负责人是沈南。",
                    source_event_ids=("source_owner",),
                    primary_source_event_id="source_owner",
                )
            )
            await tx.memory_pages.upsert(
                replace(
                    _page_memory(),
                    brief=(
                        "- 云帆看板改造项目负责人是沈南。\n"
                        "- 云帆看板改造的最终验收截止时间是 2026-04-30 18:00。"
                    ),
                    source_event_ids=("source_owner", "source_deadline"),
                    linked_memory_item_ids=("memory_owner", "memory_deadline"),
                )
            )

        current = await CurrentTruthModule(
            store,
            graph_backend=DeadlineDistractingGraphBackend(),
            now=lambda: NOW,
        ).recall_current(
            MemorySearchQuery(
                query="云帆看板改造的最终验收截止时间是什么时候？",
                scope=_scope(),
                limit=5,
                trace_id="trace_current",
            )
        )
        result = current_truth_to_access_result(
            current,
            limit=5,
            sort="relevance",
            query="云帆看板改造的最终验收截止时间是什么时候？",
        )

        assert "memory_deadline" in tuple(item.id for item in current.current_facts)
        assert result.results[0].id == "memory_deadline"
        assert result.results[1].source == "page_memory"
        assert result.results[2].source == "graph_backend"

    asyncio.run(scenario())


def test_current_truth_includes_raw_event_branch_as_last_resort_evidence() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event())

        result = await CurrentTruthModule(store, now=lambda: NOW).recall_current(
            MemorySearchQuery(
                query="Skyline",
                scope=_scope(),
                limit=10,
                trace_id="trace_current",
            )
        )

        assert result.current_facts == ()
        assert result.background == ()
        assert tuple(item.id for item in result.raw_events) == ("source_001",)
        assert result.raw_events[0].source == "source_event"
        assert result.raw_events[0].text == "Skyline was mentioned in the raw source."
        assert result.warnings == ()

    asyncio.run(scenario())


def test_current_truth_raw_event_fallback_ignores_unavailable_memory_items() -> None:
    unavailable_items = (
        _memory_item("memory_invalid", MemoryStatus.INVALID),
        replace(
            _memory_item("memory_hidden", MemoryStatus.HIDDEN),
            hidden_at=NOW,
        ),
        replace(
            _memory_item("memory_expired", MemoryStatus.ACTIVE),
            valid_to=NOW,
        ),
        replace(
            _memory_item("memory_removed", MemoryStatus.REMOVED),
            removed_at=NOW,
        ),
    )

    async def scenario(item: MemoryItem) -> None:
        store = InMemoryDataStore()
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event())
            await tx.memory_items.upsert(item)

        result = await CurrentTruthModule(store, now=lambda: NOW).recall_current(
            MemorySearchQuery(
                query="Skyline",
                scope=_scope(),
                limit=10,
                trace_id="trace_current",
            )
        )

        assert result.current_facts == ()
        assert tuple(item.id for item in result.raw_events) == ("source_001",)
        assert result.raw_events[0].source == "source_event"

    for item in unavailable_items:
        asyncio.run(scenario(item))


def test_current_truth_enriches_graph_results_with_memwing_source_links() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_graph_links.upsert(
                MemoryGraphLink(
                    id="graph_link_001",
                    backend="graphiti",
                    memory_id="memory_001",
                    source_event_id="source_001",
                    project_memory_space_id="project_001",
                    backend_space_id="project_001",
                    backend_object_type="fact",
                    backend_object_id="edge_001",
                    link_type="fact",
                    created_at=NOW,
                )
            )

        result = await CurrentTruthModule(
            store,
            graph_backend=LinkedGraphBackend(),
            now=lambda: NOW,
        ).recall_current(
            MemorySearchQuery(
                query="Skyline",
                scope=_scope(),
                limit=10,
                trace_id="trace_current",
            )
        )

        assert result.current_facts[0].id == "edge_001"
        assert result.current_facts[0].source_event_ids == ("source_001",)
        assert result.current_facts[0].memory_item_ids == ("memory_001",)

    asyncio.run(scenario())


def test_current_truth_branch_timeouts_return_warnings_without_empty_success_lie() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item("memory_active", MemoryStatus.ACTIVE))
            await tx.memory_pages.upsert(_page_memory())

        result = await CurrentTruthModule(
            store,
            graph_backend=HangingGraphBackend(),
            evidence_index=HangingEvidenceIndex(),
            graph_timeout=timedelta(milliseconds=1),
            evidence_timeout=timedelta(milliseconds=1),
            now=lambda: NOW,
        ).recall_current(
            MemorySearchQuery(
                query="Skyline",
                scope=_scope(),
                limit=10,
                trace_id="trace_current",
            )
        )

        assert tuple(item.id for item in result.current_facts) == ("memory_active",)
        assert tuple(item.id for item in result.background) == ("page_001",)
        assert result.supporting_evidence == ()
        assert [(warning.branch, warning.reason_code) for warning in result.warnings] == [
            ("graph_backend", "provider_timeout"),
            ("evidence_index", "provider_timeout"),
        ]
        assert {
            timing.branch: timing.status for timing in result.branch_timings
        }["graph_backend"] == "provider_timeout"
        assert {
            timing.branch: timing.status for timing in result.branch_timings
        }["evidence_index"] == "provider_timeout"

    asyncio.run(scenario())


def test_current_truth_fan_out_starts_remote_branches_concurrently() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        graph_started = asyncio.Event()
        evidence_started = asyncio.Event()
        result = await CurrentTruthModule(
            store,
            graph_backend=BarrierGraphBackend(
                own_started=graph_started,
                peer_started=evidence_started,
            ),
            evidence_index=BarrierEvidenceIndex(
                own_started=evidence_started,
                peer_started=graph_started,
            ),
            graph_timeout=timedelta(milliseconds=50),
            evidence_timeout=timedelta(milliseconds=50),
            now=lambda: NOW,
        ).recall_current(
            MemorySearchQuery(
                query="Skyline",
                scope=_scope(),
                limit=10,
                trace_id="trace_current",
            )
        )

        assert tuple(item.id for item in result.current_facts) == ("graph_current",)
        assert tuple(item.id for item in result.supporting_evidence) == ("evidence_current",)
        assert result.warnings == ()

    asyncio.run(scenario())


def test_current_truth_local_branch_timeout_returns_warning_without_blocking_others(
    monkeypatch,
) -> None:
    async def hang_load_memory_items(
        self,
        query: MemorySearchQuery,
    ) -> tuple[MemoryItem, ...]:
        await asyncio.Event().wait()

    monkeypatch.setattr(CurrentTruthModule, "_load_memory_items", hang_load_memory_items)
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_pages.upsert(_page_memory())

        result = await CurrentTruthModule(
            store,
            local_timeout=timedelta(milliseconds=1),
            now=lambda: NOW,
        ).recall_current(
            MemorySearchQuery(
                query="Skyline",
                scope=_scope(),
                limit=10,
                trace_id="trace_current",
            )
        )

        assert result.current_facts == ()
        assert tuple(item.id for item in result.background) == ("page_001",)
        assert [(warning.branch, warning.reason_code) for warning in result.warnings] == [
            ("memory_items", "provider_timeout"),
        ]

    asyncio.run(scenario())


class HangingGraphBackend:
    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        await asyncio.Event().wait()

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: object) -> object:
        raise NotImplementedError

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class HangingEvidenceIndex:
    async def index_source_event(self, source_event: object, scope: EffectiveScope) -> None:
        raise NotImplementedError

    async def search(self, query: MemorySearchQuery) -> MemorySearchResult:
        await asyncio.Event().wait()

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class LinkedGraphBackend:
    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        item = MemorySearchResultItem(
            id="edge_001",
            text="Skyline is current in graph.",
            score=0.9,
            source="graph_backend",
            source_event_ids=(),
            memory_item_ids=(),
            valid_from=NOW,
            valid_to=None,
            metadata={"backend": "graphiti", "backend_object_type": "entity_edge"},
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


class DeadlineDistractingGraphBackend:
    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        items = (
            MemorySearchResultItem(
                id="graph_acceptance",
                text="云帆看板改造的验收人是韩悦",
                score=None,
                source="graph_backend",
                source_event_ids=("source_acceptance",),
                memory_item_ids=("memory_acceptance",),
                valid_from=NOW,
                valid_to=None,
                metadata={},
            ),
            MemorySearchResultItem(
                id="graph_scope",
                text="云帆看板改造的交付范围包含导出入口",
                score=None,
                source="graph_backend",
                source_event_ids=("source_scope",),
                memory_item_ids=("memory_scope",),
                valid_from=NOW,
                valid_to=None,
                metadata={},
            ),
        )
        return MemorySearchResult(
            contexts=tuple(item.text for item in items),
            results=items,
            next_cursor=None,
            trace_id="graph_current",
        )

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: object) -> object:
        raise NotImplementedError

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class BarrierGraphBackend:
    def __init__(self, *, own_started: asyncio.Event, peer_started: asyncio.Event) -> None:
        self._own_started = own_started
        self._peer_started = peer_started

    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        self._own_started.set()
        await self._peer_started.wait()
        item = MemorySearchResultItem(
            id="graph_current",
            text="Skyline is current in graph.",
            score=0.9,
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


class BarrierEvidenceIndex:
    def __init__(self, *, own_started: asyncio.Event, peer_started: asyncio.Event) -> None:
        self._own_started = own_started
        self._peer_started = peer_started

    async def index_source_event(self, source_event: object, scope: EffectiveScope) -> None:
        raise NotImplementedError

    async def search(self, query: MemorySearchQuery) -> MemorySearchResult:
        self._own_started.set()
        await self._peer_started.wait()
        item = MemorySearchResultItem(
            id="evidence_current",
            text="Skyline is supported by evidence.",
            score=0.6,
            source="evidence_index",
            source_event_ids=("source_evidence",),
            memory_item_ids=(),
            valid_from=NOW,
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


def _scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=False,
        cross_group_allowed=True,
    )


def _memory_item(memory_id: str, status: MemoryStatus) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Skyline codename",
        content=f"{memory_id} says Skyline is current.",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=status,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
        original_score=0.9,
        half_life_days=30,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=0.9,
        last_decay_computed_at=NOW,
        pinned=False,
        created_by="system",
        created_at=NOW,
        activated_at=NOW if status is MemoryStatus.ACTIVE else None,
        updated_at=NOW,
        archived_at=None,
        hidden_at=None,
        invalidated_at=NOW if status is MemoryStatus.INVALID else None,
        removed_at=None,
    )


def _page_memory() -> PageMemory:
    return PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Old project background",
        brief="Earlier page memory mentions Apollo, but Skyline is current.",
        topics=(),
        open_questions=(),
        next_steps=(),
        source_event_ids=("source_page",),
        linked_memory_item_ids=(),
        version=1,
        needs_rebuild=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _source_event() -> SourceEvent:
    return SourceEvent(
        id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="feishu.message",
        content="Skyline was mentioned in the raw source.",
        content_preview="Skyline was mentioned in the raw source.",
        source_url=None,
        event_time=NOW,
        raw_payload_hash="raw_hash_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=True,
        created_at=NOW,
    )
