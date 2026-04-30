import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from memwing.application.page_memory_service import (
    PageMemoryRebuildCommand,
    PageMemorySynthesisValidationError,
    PageMemoryService,
)
from memwing.application.scope_resolver import ResolvedScope
from memwing.core.models import (
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    OutboxJob,
    PageMemory,
    PageMemorySynthesis,
    PageMemoryTopic,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest
from memwing.workers.page_memory_worker import PageMemoryWorker


NOW = datetime(2026, 4, 28, 12, tzinfo=UTC)


def test_synthesis_failure_does_not_write_fallback_or_clear_rebuild_flag() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event("source_001", "The page must remain flagged after invalid synthesis."),
    )
    _seed_pages(store, _page_memory("page_001", needs_rebuild=True))
    service = PageMemoryService(
        store,
        _FakePageMemorySynthesis(
            _synthesis(
                title="Invalid output",
                brief="",
                topic_title="Invalid topic",
                topic_summary="The brief is blank, so this output is invalid.",
            )
        ),
        clock=_FixedClock(NOW),
    )
    worker = PageMemoryWorker(
        store,
        service,
        scope_resolver=_StaticPageMemoryRebuildScopeResolver(_effective_scope()),
    )

    with pytest.raises(PageMemorySynthesisValidationError):
        asyncio.run(worker.maybe_rebuild(_outbox_job("job_001", "project_001")))

    async def persisted() -> tuple[PageMemory, int]:
        async with store.transaction() as tx:
            page = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            )
            if page is None:
                raise AssertionError("page should exist")
            return page, len(tx.state.memory_page_versions)

    page, version_count = asyncio.run(persisted())
    assert page.title == "Existing page"
    assert page.version == 1
    assert page.needs_rebuild is True
    assert version_count == 0
    assert store.audit_events == ()


def test_synthesis_topic_source_ids_must_be_covered_by_page_source_ids() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event("source_001", "The page-level source set must remain authoritative."),
        _source_event(
            "source_002",
            "A topic-only source would be missed by rebuild invalidation.",
            event_time=NOW + timedelta(minutes=1),
        ),
    )
    service = PageMemoryService(
        store,
        _FakePageMemorySynthesis(
            _synthesis(
                title="Invalid provenance",
                brief="Topic provenance must be included in page provenance.",
                topic_title="Uncovered topic source",
                topic_summary="This topic references a source missing from the page.",
                source_event_ids=("source_001",),
                topic_source_event_ids=("source_002",),
            )
        ),
        clock=_FixedClock(NOW),
    )

    with pytest.raises(PageMemorySynthesisValidationError):
        asyncio.run(
            service.rebuild(
                PageMemoryRebuildCommand(
                    scope=_effective_scope(),
                    scope_type="thread",
                    scope_id="thread_001",
                    actor_id="user_001",
                    reason="manual_rebuild",
                    trace_id="trace_invalid_topic_source",
                )
            )
        )


def test_synthesis_topic_linked_memory_ids_must_be_covered_by_page_linked_memory_ids() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event("source_001", "Linked memory provenance must remain page-visible."),
    )
    _seed_memory_items(store, _memory_item("memory_001"))
    service = PageMemoryService(
        store,
        _FakePageMemorySynthesis(
            _synthesis(
                title="Invalid linked provenance",
                brief="Topic linked memories must be included in page linked memories.",
                topic_title="Uncovered linked memory",
                topic_summary="This topic references a linked memory missing from the page.",
                linked_memory_item_ids=(),
                topic_linked_memory_item_ids=("memory_001",),
            )
        ),
        clock=_FixedClock(NOW),
    )

    with pytest.raises(PageMemorySynthesisValidationError):
        asyncio.run(
            service.rebuild(
                PageMemoryRebuildCommand(
                    scope=_effective_scope(),
                    scope_type="thread",
                    scope_id="thread_001",
                    actor_id="user_001",
                    reason="manual_rebuild",
                    trace_id="trace_invalid_topic_memory_link",
                )
            )
        )


def _seed_source_events(
    store: InMemoryDataStore,
    *events: SourceEvent,
) -> InMemoryDataStore:
    async def seed() -> None:
        async with store.transaction() as tx:
            for event in events:
                await tx.source_events.insert_if_absent(event)

    asyncio.run(seed())
    return store


def _seed_pages(
    store: InMemoryDataStore,
    *pages: PageMemory,
) -> InMemoryDataStore:
    async def seed() -> None:
        async with store.transaction() as tx:
            for page in pages:
                await tx.memory_pages.upsert(page)

    asyncio.run(seed())
    return store


def _seed_memory_items(
    store: InMemoryDataStore,
    *items: MemoryItem,
) -> InMemoryDataStore:
    async def seed() -> None:
        async with store.transaction() as tx:
            for item in items:
                await tx.memory_items.upsert(item)

    asyncio.run(seed())
    return store


def _source_event(
    source_event_id: str,
    content: str,
    *,
    event_time: datetime = NOW,
) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content=content,
        content_preview=content,
        source_url=None,
        event_time=event_time,
        raw_payload_hash=f"hash_{source_event_id}",
        metadata={"message_id": source_event_id},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=event_time,
        runtime_event_idempotency_key=f"runtime_{source_event_id}",
    )


def _page_memory(
    page_id: str,
    *,
    needs_rebuild: bool = False,
) -> PageMemory:
    return PageMemory(
        id=page_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Existing page",
        brief="Existing page content.",
        topics=(
            PageMemoryTopic(
                title="Existing topic",
                summary="Existing topic summary.",
                source_event_ids=("source_001",),
                linked_memory_item_ids=(),
            ),
        ),
        open_questions=(),
        next_steps=(),
        source_event_ids=("source_001",),
        linked_memory_item_ids=(),
        version=1,
        needs_rebuild=needs_rebuild,
        created_at=NOW,
        updated_at=NOW,
    )


def _synthesis(
    *,
    title: str,
    brief: str,
    topic_title: str,
    topic_summary: str,
    source_event_ids: tuple[str, ...] = ("source_001",),
    topic_source_event_ids: tuple[str, ...] | None = None,
    linked_memory_item_ids: tuple[str, ...] = (),
    topic_linked_memory_item_ids: tuple[str, ...] | None = None,
) -> PageMemorySynthesis:
    topic_source_ids = (
        source_event_ids if topic_source_event_ids is None else topic_source_event_ids
    )
    topic_linked_ids = (
        linked_memory_item_ids
        if topic_linked_memory_item_ids is None
        else topic_linked_memory_item_ids
    )
    return PageMemorySynthesis(
        title=title,
        brief=brief,
        topics=(
            PageMemoryTopic(
                title=topic_title,
                summary=topic_summary,
                source_event_ids=topic_source_ids,
                linked_memory_item_ids=topic_linked_ids,
            ),
        ),
        open_questions=(),
        next_steps=(),
        source_event_ids=source_event_ids,
        linked_memory_item_ids=linked_memory_item_ids,
    )


def _memory_item(memory_id: str) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Known memory",
        content="Known linked memory item.",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.ACTIVE,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
        original_score=0.8,
        half_life_days=30,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=NOW,
        activated_at=NOW,
        updated_at=NOW,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def _outbox_job(job_id: str, project_memory_space_id: str) -> OutboxJob:
    return OutboxJob(
        id=job_id,
        project_memory_space_id=project_memory_space_id,
        source_event_id="source_001",
        job_type="page_memory.maybe_rebuild",
        payload_json={"source_event_id": "source_001"},
        status="pending",
        idempotency_key=f"page_memory.maybe_rebuild:{job_id}",
        aggregate_key="source_001",
        attempts=0,
        max_attempts=3,
        priority=100,
        next_run_at=NOW,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error=None,
        dead_letter_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _effective_scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _FakePageMemorySynthesis:
    def __init__(self, synthesis: PageMemorySynthesis) -> None:
        self._synthesis = synthesis
        self.requests: list[PageMemorySynthesisRequest] = []

    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        self.requests.append(request)
        return self._synthesis


class _StaticPageMemoryRebuildScopeResolver:
    def __init__(self, scope: EffectiveScope) -> None:
        self._scope = scope

    async def resolve_page_memory_rebuild(self, page: PageMemory) -> ResolvedScope:
        return ResolvedScope(
            effective_scope=self._scope,
            source_group_id=(
                self._scope.group_ids[0] if self._scope.group_ids is not None else None
            ),
            thread_id=self._scope.thread_id,
            shared_group_id=self._scope.shared_group_id,
        )
