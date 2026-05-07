from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from memwing.application.control_service import ControlService
from memwing.application.decay_service import DEFAULT_FORGETTING_REVIEW_THRESHOLD
from memwing.application.page_memory_service import PageMemoryService
from memwing.application.push_trigger_service import PushTriggerService
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
from memwing.workers.derived_outbox_worker import (
    PUSH_CANDIDATE_SEND_JOB_TYPE,
    PUSH_CANDIDATE_TRIGGER_JOB_TYPE,
    DerivedOutboxWorker,
)


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


def test_control_plane_maintenance_pages_jobs_and_push_candidates_independently() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.push_candidates.upsert(_push_candidate(id="push_new", updated_at=NOW))
            await tx.push_candidates.upsert(
                _push_candidate(
                    id="push_old",
                    title="Older push",
                    updated_at=NOW - timedelta(days=1),
                )
            )
            await tx.outbox_jobs.enqueue(_outbox_job(id="outbox_new", updated_at=NOW))
            await tx.outbox_jobs.enqueue(
                _outbox_job(id="outbox_old", updated_at=NOW - timedelta(days=1))
            )

        first_page = await service.get_maintenance(
            scope=SCOPE,
            limit=1,
            cursor=None,
            sort="updated_at",
            trace_id="trace_push_page_1",
        )
        push_second_page = await service.get_maintenance(
            scope=SCOPE,
            limit=1,
            push_candidates_cursor=first_page.push_candidates_next_cursor,
            sort="updated_at",
            trace_id="trace_push_page_2",
        )
        jobs_second_page = await service.get_maintenance(
            scope=SCOPE,
            limit=1,
            jobs_cursor=first_page.jobs_next_cursor,
            sort="updated_at",
            trace_id="trace_jobs_page_2",
        )

        assert tuple(job.id for job in first_page.jobs) == ("outbox_new",)
        assert tuple(candidate.id for candidate in first_page.push_candidates) == ("push_new",)
        assert first_page.jobs_next_cursor == "offset:1"
        assert first_page.push_candidates_next_cursor == "offset:1"
        assert first_page.next_cursor == "offset:1"
        assert tuple(job.id for job in push_second_page.jobs) == ("outbox_new",)
        assert tuple(candidate.id for candidate in push_second_page.push_candidates) == ("push_old",)
        assert push_second_page.jobs_next_cursor == "offset:1"
        assert push_second_page.push_candidates_next_cursor is None
        assert push_second_page.next_cursor == "offset:1"
        assert tuple(job.id for job in jobs_second_page.jobs) == ("outbox_old",)
        assert tuple(candidate.id for candidate in jobs_second_page.push_candidates) == ("push_new",)
        assert jobs_second_page.jobs_next_cursor is None
        assert jobs_second_page.push_candidates_next_cursor == "offset:1"
        assert jobs_second_page.next_cursor == "offset:1"

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


def test_control_plane_sends_openclaw_feishu_runtime_push_candidates() -> None:
    store = InMemoryDataStore()
    connector = _RecordingPlatformConnector()
    service = ControlService(
        store,
        now=lambda: NOW,
        platform_connectors={"feishu": connector},
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(
                _source_event(
                    "source_001",
                    metadata={
                        "source_ref": {
                            "kind": "agent_runtime",
                            "runtime": "openclaw",
                            "session_id": "agent:main:feishu:channel:oc_group_001",
                            "message_id": "message_001",
                        },
                        "adapter_metadata": {
                            "payload": {
                                "platformRef": {
                                    "platform": "feishu",
                                    "channel_id": "oc_group_001",
                                }
                            }
                        },
                    },
                )
            )
            await tx.push_candidates.upsert(replace(_push_candidate(), status="approved"))

        sent = await service.send_push_candidate(
            candidate_id="push_001",
            platform="feishu",
            scope=SCOPE,
            actor_id="user_001",
            reason="send approved candidate",
            idempotency_key="send-openclaw-push-001",
            trace_id="trace_send_openclaw",
        )

        assert sent.status == "sent"
        assert connector.sent == (
            ("push_001", "oc_group_001", "Demo scope needs review.", "trace_send_openclaw"),
        )

    asyncio.run(scenario())


def test_control_plane_prepares_openclaw_push_card_and_acks_delivery() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.push_candidates.upsert(_push_candidate())

        card = await service.prepare_openclaw_push_card(
            scope=SCOPE,
            actor_id="openclaw",
            reason="prepare OpenClaw card",
            idempotency_key="openclaw-push-next-001",
            trace_id="trace_openclaw_push_next",
            trigger_content="提醒一下 demo 项目记忆，有什么负责人信息？",
        )

        assert card.candidate_id == "push_001"
        assert card.title == "Review Demo scope"
        assert card.presentation == {
            "title": "Review Demo scope",
            "tone": "info",
            "blocks": (
                {"type": "divider"},
                {
                    "type": "context",
                    "text": "MemWing | forgetting_review | trace trace_openclaw_push_next",
                },
            ),
        }
        assert store.push_candidates[0].status == "approved"

        ack = await service.ack_openclaw_push_card(
            candidate_id="push_001",
            scope=SCOPE,
            actor_id="openclaw",
            reason="OpenClaw queued MemWing push card",
            idempotency_key="openclaw-push-next-001:ack",
            trace_id="trace_openclaw_push_ack",
        )

        assert ack.status == "sent"
        assert any(event.stage == "control.push_candidate.openclaw_prepared" for event in store.audit_events)
        assert any(event.stage == "control.push_candidate.openclaw_sent" for event in store.audit_events)

    asyncio.run(scenario())


def test_control_plane_openclaw_push_card_prefers_memory_fact_over_summary() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.memory_items.upsert(
                replace(
                    _memory_item("memory_001", title="Demo 项目负责人"),
                    content="Demo 项目负责人: gao（高）",
                    summary="源事件最新确认了项目核心负责人信息，属于持久的项目所有者事实。",
                )
            )
            await tx.push_candidates.upsert(
                replace(
                    _push_candidate(title="Demo 项目负责人"),
                    type="decision_card",
                    content="源事件最新确认了项目核心负责人信息，属于持久的项目所有者事实。",
                    trigger_reason="decision_card",
                    trigger_source="memory_item",
                    priority=80,
                    cooldown_key="decision_card:memory_001",
                )
            )

        card = await service.prepare_openclaw_push_card(
            scope=SCOPE,
            actor_id="openclaw",
            reason="prepare OpenClaw card",
            idempotency_key="openclaw-push-next-decision-001",
            trace_id="trace_openclaw_push_decision",
            trigger_content="提醒一下 demo 项目记忆，有什么负责人信息？",
        )

        assert card.candidate_id == "push_001"
        assert card.title == "Demo 项目负责人"
        assert card.text == "Demo 项目负责人: gao（高）"
        assert card.presentation == {
            "title": "Demo 项目负责人",
            "tone": "info",
            "blocks": (
                {
                    "type": "text",
                    "text": "推送理由：源事件最新确认了项目核心负责人信息，属于持久的项目所有者事实。",
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "text": "MemWing | decision_card | trace trace_openclaw_push_decision",
                },
            ),
        }

    asyncio.run(scenario())


def test_derived_outbox_worker_auto_sends_openclaw_feishu_push_candidates() -> None:
    store = InMemoryDataStore()
    connector = _RecordingPlatformConnector()
    service = ControlService(
        store,
        now=lambda: NOW,
        platform_connectors={"feishu": connector},
    )
    worker = DerivedOutboxWorker(
        store,
        evidence_index=None,
        long_term_filter=_NoopLongTermFilterService(),
        page_memory_worker=None,
        worker_id="derived_outbox",
        control_service=service,
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(
                _source_event(
                    "source_001",
                    metadata={
                        "source_ref": {
                            "kind": "agent_runtime",
                            "runtime": "openclaw",
                            "session_id": "agent:main:feishu:channel:oc_group_001",
                        }
                    },
                )
            )
            await tx.push_candidates.upsert(_push_candidate())
            await tx.outbox_jobs.enqueue(
                replace(
                    _outbox_job(id="outbox_push_001"),
                    job_type=PUSH_CANDIDATE_SEND_JOB_TYPE,
                    payload_json={"push_candidate_id": "push_001", "platform": "feishu"},
                    aggregate_key="push_candidate.send:push_001",
                )
            )

        result = await worker.run_global_once(
            limit=1,
            job_types=(PUSH_CANDIDATE_SEND_JOB_TYPE,),
        )

        assert result.succeeded == 1
        assert connector.sent == (
            ("push_001", "oc_group_001", "Demo scope needs review.", "push_candidate:auto_send:outbox_push_001"),
        )
        assert store.push_candidates[0].status == "sent"

    asyncio.run(scenario())


def test_derived_outbox_worker_triggers_existing_candidate_from_current_feishu_context(
    tmp_path,
    monkeypatch,
) -> None:
    store = InMemoryDataStore()
    connector = _RecordingPlatformConnector()
    service = ControlService(
        store,
        now=lambda: NOW,
        platform_connectors={"feishu": connector},
    )
    worker = DerivedOutboxWorker(
        store,
        evidence_index=None,
        long_term_filter=_NoopLongTermFilterService(),
        page_memory_worker=None,
        worker_id="derived_outbox",
        control_service=service,
        push_trigger_service=PushTriggerService(store),
    )
    sessions_dir = tmp_path / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "sessions.json").write_text(
        json.dumps(
            {
                "agent:main:feishu:channel:oc_current_group": {
                    "sessionId": "runtime_session_001",
                    "deliveryContext": {
                        "channel": "feishu",
                        "to": "chat:oc_current_group",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.source_events.insert_if_absent(
                _source_event(
                    "source_trigger",
                    metadata={
                        "source_ref": {
                            "kind": "agent_runtime",
                            "runtime": "openclaw",
                            "agent_id": "main",
                            "session_id": "runtime_session_001",
                        }
                    },
                )
            )
            await tx.push_candidates.upsert(replace(_push_candidate(), status="approved"))
            await tx.outbox_jobs.enqueue(
                replace(
                    _outbox_job(id="outbox_trigger_001"),
                    source_event_id="source_trigger",
                    job_type=PUSH_CANDIDATE_TRIGGER_JOB_TYPE,
                    payload_json={"source_event_id": "source_trigger"},
                    aggregate_key="source_trigger",
                )
            )

        first = await worker.run_global_once(
            limit=1,
            job_types=(PUSH_CANDIDATE_TRIGGER_JOB_TYPE,),
        )
        second = await worker.run_global_once(
            limit=1,
            job_types=(PUSH_CANDIDATE_SEND_JOB_TYPE,),
        )

        assert first.succeeded == 1
        assert second.succeeded == 1
        assert connector.sent[0][:3] == (
            "push_001",
            "oc_current_group",
            "Demo scope needs review.",
        )
        assert connector.sent[0][3].startswith("push_candidate:auto_send:")
        assert store.push_candidates[0].status == "sent"

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


def _source_event(source_event_id: str, *, metadata: dict[str, object] | None = None) -> SourceEvent:
    content = "提醒一下 demo 项目记忆。 " if source_event_id == "source_trigger" else "Decision source text."
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
        event_time=NOW - timedelta(days=10),
        raw_payload_hash=f"hash_{source_event_id}",
        metadata=metadata or {
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
    source_event_id: str = "source_001",
    priority: int = 10,
    updated_at: datetime = NOW,
) -> OutboxJob:
    return OutboxJob(
        id=id,
        project_memory_space_id="project_001",
        source_event_id=source_event_id,
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
        serialization_key="backend:graphiti:project:project_001",
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


class _NoopLongTermFilterService:
    async def process_scope(self, command):
        raise AssertionError("long term filter should not be called")


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
