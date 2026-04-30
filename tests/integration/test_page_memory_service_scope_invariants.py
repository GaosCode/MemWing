import asyncio
from datetime import UTC, datetime

import pytest

from memwing.application.page_memory_service import (
    PageMemoryRebuildCommand,
    PageMemoryRebuildError,
    PageMemoryService,
)
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


@pytest.mark.parametrize(
    ("scope_kwargs", "scope_type", "scope_id"),
    (
        (
            {"project_memory_space_id": "project_001"},
            "project",
            "project_002",
        ),
        (
            {"group_ids": ("group_001",)},
            "group",
            "group_002",
        ),
        (
            {"thread_id": "thread_001"},
            "thread",
            "thread_002",
        ),
        (
            {},
            "meeting",
            "meeting_001",
        ),
    ),
)
def test_manual_rebuild_rejects_scope_id_that_does_not_match_effective_scope(
    scope_kwargs: dict[str, object],
    scope_type: str,
    scope_id: str,
) -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event("source_001", "Mismatched scope must not choose another page."),
    )
    service = PageMemoryService(
        store,
        _UnexpectedPageMemorySynthesis(),
        clock=_FixedClock(NOW),
    )

    with pytest.raises(PageMemoryRebuildError):
        asyncio.run(
            service.rebuild(
                PageMemoryRebuildCommand(
                    scope=_effective_scope(**scope_kwargs),
                    scope_type=scope_type,
                    scope_id=scope_id,
                    actor_id="user_001",
                    reason="manual_rebuild",
                    trace_id="trace_scope_mismatch",
                )
            )
        )


@pytest.mark.parametrize(
    "scope_kwargs",
    (
        {"group_ids": ("group_001",), "thread_id": None},
        {"group_ids": None, "thread_id": "thread_001"},
        {"group_ids": None, "thread_id": None, "shared_group_id": "shared_group_001"},
    ),
)
def test_project_page_rebuild_rejects_child_filtered_effective_scope(
    scope_kwargs: dict[str, object],
) -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event(
            "source_001",
            "A project page must not rebuild from a narrowed child scope.",
            shared_group_id=scope_kwargs.get("shared_group_id"),
        ),
    )
    service = PageMemoryService(
        store,
        _FakePageMemorySynthesis(
            _synthesis(
                title="Invalid project page rebuild",
                brief="A parent project page must not use child-filtered provenance.",
                topic_title="Invalid scope",
                topic_summary="Project rebuilds require an unfiltered project scope.",
            )
        ),
        clock=_FixedClock(NOW),
    )

    with pytest.raises(PageMemoryRebuildError):
        asyncio.run(
            service.rebuild(
                PageMemoryRebuildCommand(
                    scope=_effective_scope(**scope_kwargs),
                    scope_type="project",
                    scope_id="project_001",
                    actor_id="user_001",
                    reason="manual_rebuild",
                    trace_id="trace_project_child_scope",
                )
            )
        )


def test_group_page_rebuild_rejects_thread_filtered_effective_scope() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event("source_001", "A group page must not rebuild from a thread scope."),
    )
    service = PageMemoryService(
        store,
        _FakePageMemorySynthesis(
            _synthesis(
                title="Invalid group page rebuild",
                brief="A parent group page must not use thread-filtered provenance.",
                topic_title="Invalid scope",
                topic_summary="Group rebuilds require a group-only scope.",
            )
        ),
        clock=_FixedClock(NOW),
    )

    with pytest.raises(PageMemoryRebuildError):
        asyncio.run(
            service.rebuild(
                PageMemoryRebuildCommand(
                    scope=_effective_scope(group_ids=("group_001",), thread_id="thread_001"),
                    scope_type="group",
                    scope_id="group_001",
                    actor_id="user_001",
                    reason="manual_rebuild",
                    trace_id="trace_group_thread_scope",
                )
            )
        )


def test_group_page_rebuild_rejects_shared_group_filtered_effective_scope() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event(
            "source_001",
            "A group page must align exactly to one group scope.",
            shared_group_id="shared_group_001",
        ),
    )
    service = PageMemoryService(
        store,
        _FakePageMemorySynthesis(
            _synthesis(
                title="Invalid group page rebuild",
                brief="A group page must not use shared-group-filtered provenance.",
                topic_title="Invalid scope",
                topic_summary="Group rebuilds require exactly one group scope.",
            )
        ),
        clock=_FixedClock(NOW),
    )

    with pytest.raises(PageMemoryRebuildError):
        asyncio.run(
            service.rebuild(
                PageMemoryRebuildCommand(
                    scope=_effective_scope(
                        group_ids=("group_001",),
                        thread_id=None,
                        shared_group_id="shared_group_001",
                    ),
                    scope_type="group",
                    scope_id="group_001",
                    actor_id="user_001",
                    reason="manual_rebuild",
                    trace_id="trace_group_shared_scope",
                )
            )
        )


def test_worker_rejects_persisted_group_page_with_shared_group_scope() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event(
            "source_001",
            "Persisted group pages must not be rebuilt through shared-group scope.",
            thread_id=None,
            shared_group_id="shared_group_001",
        ),
    )
    _seed_pages(
        store,
        _page_memory(
            "page_001",
            thread_id=None,
            shared_group_id="shared_group_001",
            scope_type="group",
            scope_id="group_001",
            needs_rebuild=True,
        )
    )
    service = PageMemoryService(
        store,
        _UnexpectedPageMemorySynthesis(),
        clock=_FixedClock(NOW),
    )
    worker = PageMemoryWorker(
        store,
        service,
        scope_resolver=_StaticPageMemoryRebuildScopeResolver(
            _effective_scope(
                group_ids=("group_001",),
                thread_id=None,
                shared_group_id="shared_group_001",
            )
        ),
    )

    with pytest.raises(PageMemoryRebuildError):
        asyncio.run(worker.maybe_rebuild(_outbox_job("job_001", "project_001")))

    async def persisted() -> tuple[PageMemory, int]:
        async with store.transaction() as tx:
            page = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="group",
                scope_id="group_001",
            )
            if page is None:
                raise AssertionError("page should exist")
            return page, len(tx.state.memory_page_versions)

    page, version_count = asyncio.run(persisted())
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
    group_id: str = "group_001",
    thread_id: str | None = "thread_001",
    shared_group_id: str | None = None,
) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
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
    group_id: str = "group_001",
    thread_id: str | None = "thread_001",
    shared_group_id: str | None = None,
    scope_type: str = "thread",
    scope_id: str = "thread_001",
    needs_rebuild: bool = False,
) -> PageMemory:
    return PageMemory(
        id=page_id,
        project_memory_space_id="project_001",
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
        scope_type=scope_type,
        scope_id=scope_id,
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
) -> PageMemorySynthesis:
    return PageMemorySynthesis(
        title=title,
        brief=brief,
        topics=(
            PageMemoryTopic(
                title=topic_title,
                summary=topic_summary,
                source_event_ids=("source_001",),
                linked_memory_item_ids=(),
            ),
        ),
        open_questions=(),
        next_steps=(),
        source_event_ids=("source_001",),
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


def _effective_scope(
    *,
    project_memory_space_id: str = "project_001",
    group_ids: tuple[str, ...] | None = ("group_001",),
    thread_id: str | None = "thread_001",
    shared_group_id: str | None = None,
) -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id=project_memory_space_id,
        group_ids=group_ids,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
        safe_mode_enabled=group_ids is not None,
        cross_group_allowed=group_ids is None,
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


class _UnexpectedPageMemorySynthesis:
    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        raise AssertionError("synthesis should not be called for invalid rebuild scope")
