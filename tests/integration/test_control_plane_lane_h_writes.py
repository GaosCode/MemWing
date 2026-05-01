from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from memwing.application.control_service import ControlService
from memwing.application.decay_service import DEFAULT_FORGETTING_REVIEW_THRESHOLD
from memwing.application.page_memory_service import PageMemoryService
from memwing.core.errors import ValidationFailure
from memwing.core.models import (
    ForgettingReviewCandidate,
    GraphWriteJob,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    OutboxJob,
    PageMemory,
    PageMemorySynthesis,
    PageMemoryTopic,
    PushCandidate,
    SourceEvent,
)
from memwing.core.platform import PlatformSendResult
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore


NOW = datetime(2026, 4, 30, tzinfo=UTC)
SCOPE = EffectiveScope(
    project_memory_space_id="project_001",
    group_ids=("group_001",),
    thread_id="thread_001",
    shared_group_id=None,
    safe_mode_enabled=True,
    cross_group_allowed=False,
)
PROJECT_SCOPE = EffectiveScope(
    project_memory_space_id="project_001",
    group_ids=None,
    thread_id=None,
    shared_group_id=None,
    safe_mode_enabled=False,
    cross_group_allowed=True,
)


def test_control_plane_lists_support_cursor_sort_and_max_limit() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.memory_items.upsert(replace(_memory_item("memory_new"), updated_at=NOW))
            await tx.memory_items.upsert(
                replace(
                    _memory_item("memory_old"),
                    title="Older memory",
                    updated_at=NOW - timedelta(days=1),
                )
            )
            await tx.forgetting_review_candidates.upsert(
                _forgetting_review(review_id="review_new", memory_id="memory_new")
            )
            await tx.forgetting_review_candidates.upsert(
                _forgetting_review(
                    review_id="review_old",
                    memory_id="memory_old",
                    created_at=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(days=1),
                )
            )
            await tx.memory_pages.upsert(_page())
            await tx.memory_pages.upsert(
                replace(
                    _page(),
                    id="page_old",
                    group_id="group_old",
                    thread_id="thread_old",
                    scope_id="thread_old",
                    title="Older page",
                    created_at=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(days=1),
                )
            )
            await tx.graph_write_jobs.enqueue(_graph_job())
            await tx.outbox_jobs.enqueue(
                replace(_outbox_job(), id="outbox_job_002", updated_at=NOW - timedelta(days=1))
            )

        first_memories = await service.list_memories(
            scope=SCOPE,
            limit=1,
            cursor=None,
            sort="updated_at",
            trace_id="trace_page_1",
        )
        second_memories = await service.list_memories(
            scope=SCOPE,
            limit=1,
            cursor=first_memories.next_cursor,
            sort="updated_at",
            trace_id="trace_page_2",
        )
        reviews = await service.list_forgetting_review(
            scope=SCOPE,
            limit=500,
            cursor=None,
            sort="created_at",
            trace_id="trace_reviews",
        )
        pages = await service.list_pages(
            scope=PROJECT_SCOPE,
            limit=1,
            cursor=None,
            sort="updated_at",
            trace_id="trace_pages",
        )
        maintenance = await service.get_maintenance(
            scope=SCOPE,
            limit=1,
            cursor=None,
            sort="updated_at",
            trace_id="trace_maintenance",
        )

        assert tuple(item.id for item in first_memories.items) == ("memory_new",)
        assert first_memories.next_cursor == "offset:1"
        assert tuple(item.id for item in second_memories.items) == ("memory_old",)
        assert second_memories.next_cursor is None
        assert len(reviews.items) == 2
        assert pages.next_cursor == "offset:1"
        assert maintenance.next_cursor == "offset:1"
        assert maintenance.jobs_next_cursor == "offset:1"
        assert maintenance.push_candidates_next_cursor is None
        assert maintenance.job_count == 1

    asyncio.run(scenario())


def test_control_plane_list_sort_applies_before_limit() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.memory_items.upsert(_memory_item("memory_updated_newest", updated_at=NOW))
            await tx.memory_items.upsert(
                _memory_item(
                    "memory_middle",
                    title="Middle memory",
                    event_time=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(hours=1),
                )
            )
            await tx.memory_items.upsert(
                _memory_item(
                    "memory_event_newest",
                    title="Event newest memory",
                    event_time=NOW + timedelta(hours=1),
                    updated_at=NOW - timedelta(days=30),
                )
            )
            await tx.memory_pages.upsert(_page(id="page_updated_newest", updated_at=NOW))
            await tx.memory_pages.upsert(
                replace(
                    _page(
                        id="page_middle",
                        title="Middle page",
                        created_at=NOW - timedelta(days=1),
                        updated_at=NOW - timedelta(hours=1),
                    ),
                    group_id="group_002",
                    thread_id="thread_002",
                    scope_id="thread_002",
                )
            )
            await tx.memory_pages.upsert(
                replace(
                    _page(
                        id="page_created_newest",
                        title="Created newest page",
                        created_at=NOW + timedelta(hours=1),
                        updated_at=NOW - timedelta(days=30),
                    ),
                    group_id="group_003",
                    thread_id="thread_003",
                    scope_id="thread_003",
                )
            )
            await tx.outbox_jobs.enqueue(_outbox_job(id="outbox_updated_newest", updated_at=NOW))
            await tx.outbox_jobs.enqueue(
                _outbox_job(
                    id="outbox_middle",
                    priority=10,
                    updated_at=NOW - timedelta(hours=1),
                )
            )
            await tx.outbox_jobs.enqueue(
                _outbox_job(
                    id="outbox_priority_newest",
                    priority=999,
                    updated_at=NOW - timedelta(days=30),
                )
            )

        memories = await service.list_memories(
            scope=SCOPE,
            limit=1,
            cursor=None,
            sort="event_time",
            trace_id="trace_event_sort",
        )
        pages = await service.list_pages(
            scope=PROJECT_SCOPE,
            limit=1,
            cursor=None,
            sort="created_at",
            trace_id="trace_page_sort",
        )
        maintenance = await service.get_maintenance(
            scope=SCOPE,
            limit=1,
            cursor=None,
            sort="priority",
            trace_id="trace_job_sort",
        )

        assert tuple(item.id for item in memories.items) == ("memory_event_newest",)
        assert tuple(page.id for page in pages.items) == ("page_created_newest",)
        assert tuple(job.id for job in maintenance.jobs) == ("outbox_priority_newest",)

    asyncio.run(scenario())


def test_control_plane_maintenance_exposes_push_candidate_pagination() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.push_candidates.upsert(_push_candidate(id="push_new", created_at=NOW))
            await tx.push_candidates.upsert(
                _push_candidate(
                    id="push_old",
                    title="Older push",
                    created_at=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(days=1),
                )
            )

        first_page = await service.get_maintenance(
            scope=SCOPE,
            limit=1,
            cursor=None,
            sort="created_at",
            trace_id="trace_push_page_1",
        )
        second_page = await service.get_maintenance(
            scope=SCOPE,
            limit=1,
            cursor=first_page.push_candidates_next_cursor,
            sort="created_at",
            trace_id="trace_push_page_2",
        )

        assert first_page.jobs == ()
        assert tuple(candidate.id for candidate in first_page.push_candidates) == ("push_new",)
        assert first_page.jobs_next_cursor is None
        assert first_page.push_candidates_next_cursor == "offset:1"
        assert first_page.next_cursor == "offset:1"
        assert tuple(candidate.id for candidate in second_page.push_candidates) == ("push_old",)
        assert second_page.push_candidates_next_cursor is None
        assert second_page.next_cursor is None

    asyncio.run(scenario())


def test_control_plane_rebuilds_pages_and_sends_approved_push_candidates() -> None:
    store = InMemoryDataStore()
    connector = _RecordingPlatformConnector()
    page_service = PageMemoryService(
        store,
        _StaticPageMemorySynthesis(),
        clock=_FixedClock(NOW + timedelta(minutes=5)),
    )
    service = ControlService(
        store,
        now=lambda: NOW,
        page_memory_service=page_service,
        platform_connectors={"feishu": connector},
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.memory_items.upsert(_memory_item("memory_001"))
            await tx.memory_pages.upsert(replace(_page(), needs_rebuild=True))
            await tx.push_candidates.upsert(replace(_push_candidate(), status="approved"))

        rebuilt = await service.rebuild_page(
            page_id="page_001",
            scope=SCOPE,
            actor_id="user_001",
            reason="manual rebuild",
            idempotency_key="rebuild-page-001",
            trace_id="trace_rebuild",
        )
        sent = await service.send_push_candidate(
            candidate_id="push_001",
            platform="feishu",
            scope=SCOPE,
            actor_id="user_001",
            reason="send approved candidate",
            idempotency_key="send-push-001",
            trace_id="trace_send",
        )
        sent_again = await service.send_push_candidate(
            candidate_id="push_001",
            platform="feishu",
            scope=SCOPE,
            actor_id="user_001",
            reason="send approved candidate",
            idempotency_key="send-push-001",
            trace_id="trace_send_retry",
        )

        assert rebuilt.page.title == "Synthesized page"
        assert rebuilt.page.needs_rebuild is False
        assert rebuilt.versions[0].version == 2
        assert sent.status == "sent"
        assert sent_again.status == "sent"
        assert connector.sent == (("push_001", "oc_group_001", "Demo scope needs review.", "trace_send"),)
        assert any(event.stage == "control.page.rebuilt" for event in store.audit_events)
        assert any(event.stage == "control.push_candidate.sent" for event in store.audit_events)

    asyncio.run(scenario())


def test_control_plane_rejected_push_send_is_audited() -> None:
    store = InMemoryDataStore()
    connector = _RecordingPlatformConnector()
    service = ControlService(
        store,
        now=lambda: NOW,
        platform_connectors={"feishu": connector},
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.push_candidates.upsert(_push_candidate())

        with pytest.raises(ValidationFailure) as exc_info:
            await service.send_push_candidate(
                candidate_id="push_001",
                platform="feishu",
                scope=SCOPE,
                actor_id="user_001",
                reason="send pending candidate",
                idempotency_key="send-pending-push-001",
                trace_id="trace_pending_send",
            )

        assert exc_info.value.reason_code == "push_candidate_not_approved"
        assert connector.sent == ()
        assert any(
            event.stage == "control.push_candidate.send_rejected"
            and event.entity_id == "push_001"
            and event.idempotency_key == "send-pending-push-001"
            for event in store.audit_events
        )

    asyncio.run(scenario())


def _memory_item(
    memory_id: str,
    *,
    title: str = "Demo scope",
    event_time: datetime = NOW - timedelta(days=10),
    created_at: datetime = NOW - timedelta(days=10),
    updated_at: datetime = NOW - timedelta(days=1),
) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title=title,
        content="Demo scope remains Feishu plus OpenClaw.",
        summary="Demo scope remains stable.",
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.ACTIVE,
        event_time=event_time,
        valid_from=None,
        valid_to=None,
        original_score=0.8,
        half_life_days=10,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=created_at,
        activated_at=created_at,
        updated_at=updated_at,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def _source_event(source_event_id: str) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content="Decision source text.",
        content_preview="Decision source text.",
        source_url=None,
        event_time=NOW - timedelta(days=10),
        raw_payload_hash=f"hash_{source_event_id}",
        metadata={
            "source_ref": {
                "kind": "platform",
                "platform": "feishu",
                "tenant_id": "tenant_001",
                "channel_id": "oc_group_001",
                "thread_id": "thread_001",
                "message_id": "message_001",
            }
        },
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW - timedelta(days=10),
        runtime_event_idempotency_key=None,
    )


def _page(
    *,
    id: str = "page_001",
    title: str = "Current title",
    created_at: datetime = NOW,
    updated_at: datetime = NOW,
) -> PageMemory:
    return PageMemory(
        id=id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title=title,
        brief="Current brief",
        topics=(
            PageMemoryTopic(
                title="Demo",
                summary="Demo scope remains stable.",
                source_event_ids=("source_001",),
                linked_memory_item_ids=("memory_001",),
            ),
        ),
        open_questions=("What ships next?",),
        next_steps=("Review scope",),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
        version=1,
        needs_rebuild=False,
        created_at=created_at,
        updated_at=updated_at,
    )


def _forgetting_review(
    *,
    review_id: str,
    memory_id: str,
    created_at: datetime = NOW,
    updated_at: datetime = NOW,
) -> ForgettingReviewCandidate:
    return ForgettingReviewCandidate(
        id=review_id,
        memory_id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        decayed_score=0.4,
        threshold=DEFAULT_FORGETTING_REVIEW_THRESHOLD,
        reason="score_below_threshold",
        status="pending",
        created_at=created_at,
        updated_at=updated_at,
    )


def _push_candidate(
    *,
    id: str = "push_001",
    title: str = "Review Demo scope",
    created_at: datetime = NOW,
    updated_at: datetime = NOW,
) -> PushCandidate:
    return PushCandidate(
        id=id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        type="forgetting_review",
        title=title,
        content="Demo scope needs review.",
        memory_item_ids=("memory_001",),
        source_event_ids=("source_001",),
        trigger_reason="score_below_threshold",
        trigger_source="forgetting_review",
        priority=100,
        expires_at=None,
        status="pending",
        cooldown_key=f"forgetting_review:{id}",
        created_at=created_at,
        updated_at=updated_at,
    )


def _outbox_job(
    *,
    id: str = "outbox_job_001",
    priority: int = 10,
    updated_at: datetime = NOW,
) -> OutboxJob:
    return OutboxJob(
        id=id,
        project_memory_space_id="project_001",
        source_event_id="source_001",
        job_type="memory.decay",
        payload_json={},
        status="pending",
        idempotency_key=f"outbox:memory.decay:{id}",
        aggregate_key="project_001",
        attempts=0,
        max_attempts=3,
        priority=priority,
        next_run_at=NOW,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error=None,
        dead_letter_reason=None,
        created_at=NOW,
        updated_at=updated_at,
    )


def _graph_job() -> GraphWriteJob:
    return GraphWriteJob(
        id="graph_job_001",
        backend="graphiti",
        project_memory_space_id="project_001",
        thread_id="thread_001",
        saga_id=None,
        memory_id="memory_001",
        source_event_ids=("source_001",),
        route=MemoryRoute.GRAPH,
        status="dead_letter",
        idempotency_key="graph:memory_001",
        attempts=1,
        max_attempts=3,
        priority=100,
        next_run_at=NOW,
        dead_letter_reason="ProviderPermanentFailure",
        last_error="ProviderPermanentFailure",
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _StaticPageMemorySynthesis:
    async def synthesize(self, request) -> PageMemorySynthesis:
        return PageMemorySynthesis(
            title="Synthesized page",
            brief="Synthesized brief.",
            topics=(
                PageMemoryTopic(
                    title="Synthesized topic",
                    summary="Synthesized summary.",
                    source_event_ids=("source_001",),
                    linked_memory_item_ids=("memory_001",),
                ),
            ),
            open_questions=(),
            next_steps=("Send update",),
            source_event_ids=("source_001",),
            linked_memory_item_ids=("memory_001",),
        )


class _RecordingPlatformConnector:
    def __init__(self) -> None:
        self.sent: tuple[tuple[str, str, str, str], ...] = ()

    async def verify_request(self, raw_request) -> bool:
        raise AssertionError("verify_request should not be called")

    async def normalize_event(self, raw_event):
        raise AssertionError("normalize_event should not be called")

    async def send_candidate(self, candidate) -> PlatformSendResult:
        self.sent = (
            *self.sent,
            (
                candidate.id,
                candidate.platform_ref.channel_id,
                candidate.content,
                candidate.trace_id,
            ),
        )
        return PlatformSendResult(
            candidate_id=candidate.id,
            delivered=True,
            trace_id=candidate.trace_id,
            provider_message_id="sent_001",
        )
