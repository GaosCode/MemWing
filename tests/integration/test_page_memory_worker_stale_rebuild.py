import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.application.page_memory_service import PageMemoryService
from memwing.application.scope_resolver import ResolvedScope
from memwing.core.models import (
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


def test_worker_skips_stale_needs_rebuild_when_current_page_is_already_rebuilt() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event(
            "source_current",
            "A concurrent worker may rebuild this page before this worker writes.",
        ),
    )
    _seed_pages(
        store,
        _page_memory(
            "page_001",
            source_event_ids=("source_current",),
            needs_rebuild=True,
        ),
    )
    synthesis = _ConcurrentNeedsRebuildClearedSynthesis(store)
    service = PageMemoryService(store, synthesis, clock=_FixedClock(NOW + timedelta(minutes=1)))
    worker = PageMemoryWorker(
        store,
        service,
        scope_resolver=_StaticPageMemoryRebuildScopeResolver(_effective_scope()),
    )

    result = asyncio.run(worker.maybe_rebuild(_outbox_job("job_001")))

    assert result.scanned == 1
    assert result.rebuilt == 0

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
    assert page.title == "Already rebuilt"
    assert page.version == 2
    assert page.needs_rebuild is False
    assert version_count == 0
    assert store.audit_events == ()


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


def _source_event(source_event_id: str, content: str) -> SourceEvent:
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
        event_time=NOW,
        raw_payload_hash=f"hash_{source_event_id}",
        metadata={"message_id": source_event_id},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
        runtime_event_idempotency_key=f"runtime_{source_event_id}",
    )


def _page_memory(
    page_id: str,
    *,
    source_event_ids: tuple[str, ...],
    needs_rebuild: bool,
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
                source_event_ids=source_event_ids,
                linked_memory_item_ids=(),
            ),
        ),
        open_questions=(),
        next_steps=(),
        source_event_ids=source_event_ids,
        linked_memory_item_ids=(),
        version=1,
        needs_rebuild=needs_rebuild,
        created_at=NOW,
        updated_at=NOW,
    )


def _outbox_job(job_id: str) -> OutboxJob:
    return OutboxJob(
        id=job_id,
        project_memory_space_id="project_001",
        source_event_id="source_current",
        job_type="page_memory.maybe_rebuild",
        payload_json={"source_event_id": "source_current"},
        status="pending",
        idempotency_key=f"page_memory.maybe_rebuild:{job_id}",
        aggregate_key="source_current",
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


class _ConcurrentNeedsRebuildClearedSynthesis:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        if request.existing_page is None:
            raise AssertionError("test requires an existing page")
        rebuilt = replace(
            request.existing_page,
            title="Already rebuilt",
            version=2,
            needs_rebuild=False,
            updated_at=NOW + timedelta(seconds=30),
        )
        async with self._store.transaction() as tx:
            await tx.memory_pages.upsert(rebuilt)
        source_event_ids = tuple(event.id for event in request.source_events)
        return PageMemorySynthesis(
            title="Stale rebuild",
            brief="This stale synthesis must not overwrite the current page.",
            topics=(
                PageMemoryTopic(
                    title="Stale topic",
                    summary="The service must re-check the current page before writing.",
                    source_event_ids=source_event_ids,
                    linked_memory_item_ids=(),
                ),
            ),
            open_questions=(),
            next_steps=(),
            source_event_ids=source_event_ids,
            linked_memory_item_ids=(),
        )
