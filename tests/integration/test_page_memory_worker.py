import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from memwing.application.page_memory_service import (
    PageMemoryRebuildCommand,
    PageMemorySynthesisValidationError,
    PageMemoryService,
)
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


def test_manual_rebuild_creates_page_and_version_from_source_events() -> None:
    store = InMemoryDataStore()
    store_with_sources = _seed_source_events(
        store,
        _source_event("source_001", "First decision keeps Page Memory scoped."),
        _source_event(
            "source_002",
            "Second decision requires model synthesis for the page.",
            event_time=NOW + timedelta(minutes=1),
        ),
    )
    synthesis = _FakePageMemorySynthesis(
        _synthesis(
            title="Page Memory lane",
            brief="The lane rebuilds a project mainline from source events.",
            topic_title="Rebuild path",
            topic_summary="Manual rebuild reads ordered source events and writes a page.",
            open_questions=("How should later control-plane rebuilds pass actors?",),
            next_steps=("Wire the maybe_rebuild worker.",),
            source_event_ids=("source_001", "source_002"),
        )
    )
    service = PageMemoryService(store_with_sources, synthesis, clock=_FixedClock(NOW))

    result = asyncio.run(
        service.rebuild(
            PageMemoryRebuildCommand(
                scope=_effective_scope(),
                scope_type="thread",
                scope_id="thread_001",
                actor_id="user_001",
                reason="manual_rebuild",
                trace_id="trace_manual_rebuild",
            )
        )
    )

    assert result.page.title == "Page Memory lane"
    assert result.page.source_event_ids == ("source_001", "source_002")
    assert result.page.needs_rebuild is False
    assert result.version.page_id == result.page.id
    assert result.version.version == 1
    assert result.audit_event.stage == "page_memory.rebuilt"
    assert result.audit_event.actor_id == "user_001"
    assert synthesis.requests[0].scope == _effective_scope()
    assert tuple(event.id for event in synthesis.requests[0].source_events) == (
        "source_001",
        "source_002",
    )

    async def persisted() -> tuple[int, str]:
        async with store_with_sources.transaction() as tx:
            page = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            )
            return len(tx.state.memory_page_versions), page.id if page is not None else ""

    version_count, page_id = asyncio.run(persisted())
    assert version_count == 1
    assert page_id == result.page.id
    assert store_with_sources.audit_events[-1] == result.audit_event


def test_needs_rebuild_scanner_rebuilds_flagged_pages_and_clears_flag() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event("source_001", "Project one needs its thread page rebuilt."),
        _source_event(
            "source_other",
            "Another project should not be scanned by this job.",
            project_memory_space_id="project_002",
            group_id="group_002",
            thread_id="thread_002",
        ),
    )
    _seed_pages(
        store,
        _page_memory("page_001", needs_rebuild=True),
        _page_memory(
            "page_other",
            project_memory_space_id="project_002",
            group_id="group_002",
            thread_id="thread_002",
            scope_id="thread_002",
            source_event_ids=("source_other",),
            needs_rebuild=True,
        ),
    )
    synthesis = _FakePageMemorySynthesis(
        _synthesis(
            title="Rebuilt project page",
            brief="The project page was rebuilt from current source events.",
            topic_title="Rebuild",
            topic_summary="The flagged page is rebuilt by the worker.",
            next_steps=("Keep the other project untouched.",),
        )
    )
    service = PageMemoryService(store, synthesis, clock=_FixedClock(NOW))
    worker = PageMemoryWorker(store, service)

    result = asyncio.run(worker.maybe_rebuild(_outbox_job("job_001", "project_001")))

    assert result.scanned == 1
    assert result.rebuilt == 1
    assert synthesis.requests[0].existing_page is not None
    assert synthesis.requests[0].existing_page.id == "page_001"

    async def persisted() -> tuple[PageMemory, PageMemory, int]:
        async with store.transaction() as tx:
            rebuilt = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            )
            untouched = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_002",
                scope_type="thread",
                scope_id="thread_002",
            )
            return (
                rebuilt,
                untouched,
                len(tx.state.memory_page_versions),
            )

    rebuilt_page, untouched_page, version_count = asyncio.run(persisted())
    assert rebuilt_page.title == "Rebuilt project page"
    assert rebuilt_page.version == 2
    assert rebuilt_page.needs_rebuild is False
    assert untouched_page.version == 1
    assert untouched_page.needs_rebuild is True
    assert version_count == 1
    assert store.audit_events[-1].reason_code == "needs_rebuild"


def test_page_memory_maybe_rebuild_noops_when_no_page_needs_rebuild() -> None:
    store = InMemoryDataStore()
    service = PageMemoryService(
        store,
        _UnexpectedPageMemorySynthesis(),
        clock=_FixedClock(NOW),
    )
    worker = PageMemoryWorker(store, service)

    result = asyncio.run(worker.maybe_rebuild(_outbox_job("job_001", "project_001")))

    assert result.scanned == 0
    assert result.rebuilt == 0
    assert store.audit_events == ()


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
    worker = PageMemoryWorker(store, service)

    with pytest.raises(PageMemorySynthesisValidationError):
        asyncio.run(worker.maybe_rebuild(_outbox_job("job_001", "project_001")))

    async def persisted() -> tuple[PageMemory, int]:
        async with store.transaction() as tx:
            page = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            )
            return page, len(tx.state.memory_page_versions)

    page, version_count = asyncio.run(persisted())
    assert page.title == "Existing page"
    assert page.version == 1
    assert page.needs_rebuild is True
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


def _source_event(
    source_event_id: str,
    content: str,
    *,
    event_time: datetime = NOW,
    project_memory_space_id: str = "project_001",
    group_id: str = "group_001",
    thread_id: str = "thread_001",
) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id=project_memory_space_id,
        group_id=group_id,
        thread_id=thread_id,
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
    project_memory_space_id: str = "project_001",
    group_id: str = "group_001",
    thread_id: str = "thread_001",
    scope_id: str = "thread_001",
    source_event_ids: tuple[str, ...] = ("source_001",),
    needs_rebuild: bool = False,
) -> PageMemory:
    return PageMemory(
        id=page_id,
        project_memory_space_id=project_memory_space_id,
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=None,
        scope_type="thread",
        scope_id=scope_id,
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


def _synthesis(
    *,
    title: str,
    brief: str,
    topic_title: str,
    topic_summary: str,
    source_event_ids: tuple[str, ...] = ("source_001",),
    open_questions: tuple[str, ...] = (),
    next_steps: tuple[str, ...] = (),
) -> PageMemorySynthesis:
    return PageMemorySynthesis(
        title=title,
        brief=brief,
        topics=(
            PageMemoryTopic(
                title=topic_title,
                summary=topic_summary,
                source_event_ids=source_event_ids,
                linked_memory_item_ids=(),
            ),
        ),
        open_questions=open_questions,
        next_steps=next_steps,
        source_event_ids=source_event_ids,
        linked_memory_item_ids=(),
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


class _UnexpectedPageMemorySynthesis:
    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        raise AssertionError("synthesis should not be called when no page needs rebuild")
