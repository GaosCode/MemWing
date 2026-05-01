import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.application.current_truth import CurrentTruthModule
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult
from memwing.core.models import (
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
        assert result.trace_id == "trace_current"

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
        assert result.raw_events[0].source == "raw_event"
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
        assert result.raw_events[0].source == "raw_event"

    for item in unavailable_items:
        asyncio.run(scenario(item))


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

    asyncio.run(scenario())


def test_current_truth_local_branch_timeout_returns_warning_without_blocking_others(
    monkeypatch,
) -> None:
    from memwing.infrastructure.db.in_memory_memory_repositories import (
        InMemoryMemoryItemRepository,
    )

    async def hang_list_for_scope(self, *, scope, limit):
        await asyncio.Event().wait()

    monkeypatch.setattr(InMemoryMemoryItemRepository, "list_for_scope", hang_list_for_scope)
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
