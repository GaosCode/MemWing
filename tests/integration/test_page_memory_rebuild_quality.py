import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.application.page_memory_service import (
    PageMemoryRebuildCommand,
    PageMemoryService,
)
from memwing.core.models import (
    PageMemory,
    PageMemorySynthesis,
    PageMemoryTopic,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest


NOW = datetime(2026, 4, 28, 12, tzinfo=UTC)


def test_rebuild_source_event_limit_uses_latest_events_for_synthesis() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event(
            "source_old",
            "The old decision should fall outside the latest rebuild window.",
            event_time=NOW,
        ),
        _source_event(
            "source_new",
            "The new decision should be synthesized when the limit is one.",
            event_time=NOW + timedelta(minutes=1),
        ),
    )
    synthesis = _EchoSourceEventSynthesis()
    service = PageMemoryService(
        store,
        synthesis,
        clock=_FixedClock(NOW + timedelta(minutes=2)),
        source_event_limit=1,
    )

    result = asyncio.run(
        service.rebuild(
            PageMemoryRebuildCommand(
                scope=_effective_scope(),
                scope_type="thread",
                scope_id="thread_001",
                actor_id="user_001",
                reason="manual_rebuild",
                trace_id="trace_latest_source_window",
            )
        )
    )

    assert tuple(event.id for event in synthesis.requests[0].source_events) == ("source_new",)
    assert result.page.source_event_ids == ("source_new",)


def test_rebuild_writes_version_from_current_locked_page_after_synthesis() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event(
            "source_current",
            "The rebuild should be based on the page version locked at write time.",
        ),
    )
    _seed_pages(
        store,
        _page_memory(
            "page_001",
            source_event_ids=("source_current",),
            version=1,
        ),
    )
    synthesis = _ConcurrentPageUpdateSynthesis(store, concurrent_version=4)
    service = PageMemoryService(store, synthesis, clock=_FixedClock(NOW + timedelta(minutes=1)))

    result = asyncio.run(
        service.rebuild(
            PageMemoryRebuildCommand(
                scope=_effective_scope(),
                scope_type="thread",
                scope_id="thread_001",
                actor_id="user_001",
                reason="manual_rebuild",
                trace_id="trace_current_locked_version",
            )
        )
    )

    assert synthesis.existing_page_versions == (1,)
    assert result.page.version == 5
    assert result.version.version == 5

    async def persisted_version() -> int:
        async with store.transaction() as tx:
            page = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            )
            if page is None:
                raise AssertionError("page should exist")
            return page.version

    assert asyncio.run(persisted_version()) == 5


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


def _source_event(
    source_event_id: str,
    content: str,
    *,
    event_time: datetime = NOW,
    group_id: str = "group_001",
) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id=group_id,
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
    group_id: str = "group_001",
    source_event_ids: tuple[str, ...] = ("source_authority",),
    version: int = 1,
    needs_rebuild: bool = False,
) -> PageMemory:
    return PageMemory(
        id=page_id,
        project_memory_space_id="project_001",
        group_id=group_id,
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
        version=version,
        needs_rebuild=needs_rebuild,
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


class _EchoSourceEventSynthesis:
    def __init__(self) -> None:
        self.requests: list[PageMemorySynthesisRequest] = []

    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        self.requests.append(request)
        source_event_ids = tuple(event.id for event in request.source_events)
        return PageMemorySynthesis(
            title="Latest rebuild window",
            brief="The page was rebuilt from the latest eligible source events.",
            topics=(
                PageMemoryTopic(
                    title="Latest source",
                    summary="The synthesis input uses the newest source window.",
                    source_event_ids=source_event_ids,
                    linked_memory_item_ids=(),
                ),
            ),
            open_questions=(),
            next_steps=(),
            source_event_ids=source_event_ids,
            linked_memory_item_ids=(),
        )


class _ConcurrentPageUpdateSynthesis:
    def __init__(
        self,
        store: InMemoryDataStore,
        *,
        concurrent_version: int,
    ) -> None:
        self._store = store
        self._concurrent_version = concurrent_version
        self.existing_page_versions: tuple[int | None, ...] = ()

    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        self.existing_page_versions = (
            *self.existing_page_versions,
            request.existing_page.version if request.existing_page is not None else None,
        )
        if request.existing_page is None:
            raise AssertionError("test requires an existing page")

        async with self._store.transaction() as tx:
            await tx.memory_pages.upsert(
                replace(
                    request.existing_page,
                    title="Concurrent update",
                    version=self._concurrent_version,
                    updated_at=NOW + timedelta(seconds=30),
                )
            )

        source_event_ids = tuple(event.id for event in request.source_events)
        return PageMemorySynthesis(
            title="Rebuilt after concurrent update",
            brief="The rebuild should advance from the locked current version.",
            topics=(
                PageMemoryTopic(
                    title="Current version",
                    summary="The write path must use the current page version.",
                    source_event_ids=source_event_ids,
                    linked_memory_item_ids=(),
                ),
            ),
            open_questions=(),
            next_steps=(),
            source_event_ids=source_event_ids,
            linked_memory_item_ids=(),
        )
