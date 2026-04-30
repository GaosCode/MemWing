import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.application.page_memory_service import (
    PageMemoryRebuildCommand,
    PageMemoryService,
)
from memwing.core.models import (
    MemoryPageVersion,
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


def test_rebuild_locks_scope_before_first_create_write_version() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event(
            "source_current",
            "The second first-create rebuild must advance after the first page appears.",
        ),
    )
    competing_page = _page_memory(
        "page_competing",
        source_event_ids=("source_current",),
        version=1,
    )
    race_store = _FirstCreateRaceDataStore(store, competing_page)
    synthesis = _EchoSourceEventSynthesis()
    service = PageMemoryService(race_store, synthesis, clock=_FixedClock(NOW))

    result = asyncio.run(
        service.rebuild(
            PageMemoryRebuildCommand(
                scope=_effective_scope(),
                scope_type="thread",
                scope_id="thread_001",
                actor_id="user_001",
                reason="manual_rebuild",
                trace_id="trace_first_create_race",
            )
        )
    )

    assert synthesis.requests[0].existing_page is None
    assert result.page.version == 2
    assert result.version.version == 2
    assert result.audit_event.entity_id == result.page.id
    assert result.audit_event.output_ref == result.page.id
    assert result.audit_event.source_event_ids == result.page.source_event_ids

    async def persisted() -> tuple[PageMemory, tuple[MemoryPageVersion, ...]]:
        async with store.transaction() as tx:
            page = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            )
            if page is None:
                raise AssertionError("page should exist")
            versions = tuple(tx.state.memory_page_versions.values())
            return page, versions

    page, versions = asyncio.run(persisted())
    assert page.version == 2
    assert {version.version for version in versions} == {1, 2}
    assert page.title == result.version.title
    assert page.brief == result.version.brief


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


def _page_version(page: PageMemory) -> MemoryPageVersion:
    return MemoryPageVersion(
        id=f"memory_page_version_{page.id}_{page.version}",
        page_id=page.id,
        version=page.version,
        title=page.title,
        brief=page.brief,
        topics=page.topics,
        open_questions=page.open_questions,
        next_steps=page.next_steps,
        source_event_ids=page.source_event_ids,
        linked_memory_item_ids=page.linked_memory_item_ids,
        changed_by="system",
        change_reason="manual_rebuild",
        created_at=page.updated_at,
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


class _FirstCreateRaceDataStore:
    def __init__(
        self,
        store: InMemoryDataStore,
        competing_page: PageMemory,
    ) -> None:
        self._store = store
        self._competing_page = competing_page
        self._competing_page_inserted = False
        self._scope_locked = False
        self._stale_no_page_read = False

    def transaction(self) -> "_FirstCreateRaceTransaction":
        return _FirstCreateRaceTransaction(self, self._store.transaction())

    def insert_competing_page(self, tx: object) -> None:
        if self._competing_page_inserted:
            return
        state = tx.state
        page = self._competing_page
        state.memory_pages[page.id] = page
        state.memory_page_by_scope[
            (page.project_memory_space_id, page.scope_type, page.scope_id)
        ] = page.id
        version = _page_version(page)
        state.memory_page_versions[version.id] = version
        state.memory_page_version_by_page_version[(version.page_id, version.version)] = version.id
        self._competing_page_inserted = True


class _FirstCreateRaceTransaction:
    def __init__(
        self,
        race_store: _FirstCreateRaceDataStore,
        inner: object,
    ) -> None:
        self._race_store = race_store
        self._inner = inner

    async def __aenter__(self) -> "_FirstCreateRaceTransaction":
        tx = await self._inner.__aenter__()
        self._tx = tx
        self.source_events = tx.source_events
        self.audit_events = tx.audit_events
        self.outbox_jobs = tx.outbox_jobs
        self.evidence_chunks = tx.evidence_chunks
        self.working_memory_entries = tx.working_memory_entries
        self.memory_items = tx.memory_items
        self.memory_versions = tx.memory_versions
        self.memory_pages = _FirstCreateRaceMemoryPageRepository(
            self._race_store,
            tx.memory_pages,
            tx,
        )
        self.memory_page_versions = tx.memory_page_versions
        self.graph_write_jobs = tx.graph_write_jobs
        self.memory_graph_links = tx.memory_graph_links
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return await self._inner.__aexit__(exc_type, exc, traceback)


class _FirstCreateRaceMemoryPageRepository:
    def __init__(
        self,
        race_store: _FirstCreateRaceDataStore,
        inner: object,
        tx: object,
    ) -> None:
        self._race_store = race_store
        self._inner = inner
        self._tx = tx

    async def upsert(self, page: PageMemory) -> PageMemory:
        if self._race_store._stale_no_page_read:
            self._race_store.insert_competing_page(self._tx)
        return await self._inner.upsert(page)

    async def lock_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: str,
        scope_id: str,
    ) -> None:
        self._race_store._scope_locked = True
        self._race_store.insert_competing_page(self._tx)
        await self._inner.lock_scope(
            project_memory_space_id=project_memory_space_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )

    async def get_by_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: str,
        scope_id: str,
    ) -> PageMemory | None:
        return await self._inner.get_by_scope(
            project_memory_space_id=project_memory_space_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )

    async def get_by_scope_for_update(
        self,
        *,
        project_memory_space_id: str,
        scope_type: str,
        scope_id: str,
    ) -> PageMemory | None:
        page = await self._inner.get_by_scope_for_update(
            project_memory_space_id=project_memory_space_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        if page is None and not self._race_store._scope_locked:
            self._race_store._stale_no_page_read = True
        return page

    async def mark_needs_rebuild_for_source(
        self,
        *,
        source_event_id: str,
        updated_at: datetime,
    ) -> int:
        return await self._inner.mark_needs_rebuild_for_source(
            source_event_id=source_event_id,
            updated_at=updated_at,
        )

    async def list_needs_rebuild(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PageMemory, ...]:
        return await self._inner.list_needs_rebuild(
            project_memory_space_id=project_memory_space_id,
            limit=limit,
        )


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
