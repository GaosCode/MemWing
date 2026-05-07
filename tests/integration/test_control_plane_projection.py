from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from memwing.application.control_service import ControlService
from memwing.application.decay_service import DEFAULT_FORGETTING_REVIEW_THRESHOLD
from memwing.core.errors import ScopeResolutionFailure
from memwing.core.models import (
    AuditEvent,
    ForgettingReviewCandidate,
    GraphWriteJob,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryItem,
    MemoryPageVersion,
    PageMemory,
    PageMemoryTopic,
    MemoryRoute,
    MemoryStatus,
    OutboxJob,
    PushCandidate,
    SourceEvent,
)
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


def test_control_plane_projection_lists_detail_and_maintenance_models() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.source_events.insert_if_absent(
                replace(_source_event("source_other"), group_id="group_other")
            )
            await tx.source_events.insert_if_absent(
                replace(
                    _source_event("source_redacted"),
                    purge_level="memwing_redaction",
                    graph_backend_raw_retained=True,
                )
            )
            await tx.memory_items.upsert(
                replace(
                    _memory_item("memory_001"),
                    source_event_ids=("source_001", "source_redacted"),
                    original_score=0.8,
                    half_life_days=10,
                    activated_at=NOW - timedelta(days=10),
                    last_reviewed_at=None,
                    last_confirmed_at=None,
                )
            )
            await tx.memory_items.upsert(
                replace(
                    _memory_item("memory_other"),
                    group_id="group_other",
                    thread_id="thread_001",
                )
            )
            await tx.memory_graph_links.upsert(_graph_link())
            await tx.audit_events.record(_audit_event("audit_001", entity_id="memory_001"))
            await tx.forgetting_review_candidates.upsert(_forgetting_review())
            await tx.forgetting_review_candidates.upsert(
                _forgetting_review(
                    review_id="forgetting_review_other",
                    memory_id="memory_other",
                    group_id="group_other",
                )
            )
            await tx.push_candidates.upsert(_push_candidate())
            await tx.outbox_jobs.enqueue(_outbox_job())
            await tx.outbox_jobs.enqueue(
                replace(
                    _outbox_job(),
                    id="outbox_job_other",
                    source_event_id="source_other",
                    idempotency_key="outbox:memory.decay:project_001:other",
                )
            )
            await tx.graph_write_jobs.enqueue(_graph_job())
            await tx.graph_write_jobs.enqueue(
                replace(
                    _graph_job(),
                    id="graph_job_other",
                    memory_id="memory_other",
                    source_event_ids=("source_other",),
                    idempotency_key="graph:memory_other",
                )
            )

        memory_list = await service.list_memories(scope=SCOPE, limit=10, trace_id="trace_list")
        detail = await service.get_memory_detail(
            memory_id="memory_001",
            scope=SCOPE,
            trace_id="trace_detail",
        )
        reviews = await service.list_forgetting_review(
            scope=SCOPE,
            limit=10,
            trace_id="trace_review",
        )
        maintenance = await service.get_maintenance(
            scope=SCOPE,
            limit=10,
            trace_id="trace_maintenance",
        )

        assert tuple(item.id for item in memory_list.items) == ("memory_001",)
        item = memory_list.items[0]
        assert item.decay_score == pytest.approx(0.4)
        assert item.recall_threshold == DEFAULT_FORGETTING_REVIEW_THRESHOLD
        assert item.curve_state == "below_threshold"
        assert item.retention_reason == "score_below_recall_threshold"
        assert item.next_review_at == NOW
        assert item.flags == ("needs_review", "graph_linked", "source_redacted")
        assert item.graph_backend_raw_retained is True
        assert item.available_actions == ("confirm", "archive", "hide", "pin")

        assert detail.item.id == "memory_001"
        assert detail.source_event_ids == ("source_001", "source_redacted")
        assert detail.memory_item_ids == ("memory_001",)
        assert tuple(link.backend_object_id for link in detail.graph_links) == ("edge_001",)
        assert detail.audit_refs == ("audit_001",)

        assert tuple(review.id for review in reviews.items) == ("forgetting_review_001",)
        assert reviews.items[0].memory.decay_score == pytest.approx(item.decay_score)
        assert reviews.items[0].threshold == DEFAULT_FORGETTING_REVIEW_THRESHOLD

        assert maintenance.forgetting_review_count == 1
        assert maintenance.pending_push_count == 1
        assert maintenance.job_count == 2
        assert tuple(job.id for job in maintenance.jobs) == ("graph_job_001", "outbox_job_001")
        assert maintenance.jobs[0].retryable is False
        assert maintenance.push_candidates[0].id == "push_001"

    asyncio.run(scenario())


def test_control_plane_detail_uses_safe_non_leaky_scope_errors() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item("memory_001"))
            await tx.memory_items.upsert(
                replace(
                    _memory_item("memory_other"),
                    group_id="group_other",
                    thread_id="thread_001",
                )
            )

        missing_error: ScopeResolutionFailure | None = None
        out_of_scope_error: ScopeResolutionFailure | None = None
        try:
            await service.get_memory_detail(
                memory_id="missing_memory",
                scope=SCOPE,
                trace_id="trace_missing",
            )
        except ScopeResolutionFailure as exc:
            missing_error = exc
        try:
            await service.get_memory_detail(
                memory_id="memory_other",
                scope=SCOPE,
                trace_id="trace_scope",
            )
        except ScopeResolutionFailure as exc:
            out_of_scope_error = exc

        assert missing_error is not None
        assert out_of_scope_error is not None
        assert missing_error.reason_code == out_of_scope_error.reason_code
        assert missing_error.safe_message == out_of_scope_error.safe_message
        assert "memory_other" not in out_of_scope_error.safe_message

    asyncio.run(scenario())


def test_control_plane_page_edit_restore_push_and_job_retry() -> None:
    store = InMemoryDataStore()
    service = ControlService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.memory_pages.upsert(_page())
            await tx.memory_page_versions.record(_page_version(version=1, title="Old title"))
            await tx.push_candidates.upsert(_push_candidate())
            await tx.graph_write_jobs.enqueue(_graph_job())

        edited = await service.edit_page(
            page_id="page_001",
            scope=SCOPE,
            title="Edited title",
            brief="Edited brief",
            actor_id="user_001",
            reason="manual edit",
            idempotency_key="edit-page-001",
            trace_id="trace_edit",
        )
        assert edited.page.title == "Edited title"
        assert edited.versions[0].version == 2

        restored = await service.restore_page_version(
            page_id="page_001",
            version=1,
            scope=SCOPE,
            actor_id="user_001",
            reason="restore old version",
            idempotency_key="restore-page-001",
            trace_id="trace_restore",
        )
        assert restored.page.title == "Old title"
        assert restored.versions[0].version == 3

        approved = await service.approve_push_candidate(
            candidate_id="push_001",
            scope=SCOPE,
            actor_id="user_001",
            reason="approve candidate",
            idempotency_key="approve-push-001",
            trace_id="trace_push",
        )
        assert approved.status == "approved"

        maintenance = await service.retry_job(
            job_id="graph_job_001",
            kind="graph_write",
            scope=SCOPE,
            actor_id="user_001",
            reason="retry graph job",
            idempotency_key="retry-graph-001",
            trace_id="trace_retry",
        )
        assert maintenance.jobs[0].id == "graph_job_001"
        assert maintenance.jobs[0].status == "pending"

    asyncio.run(scenario())


def _memory_item(memory_id: str) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Demo scope",
        content="Demo scope remains Feishu plus OpenClaw.",
        summary="Demo scope remains stable.",
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.ACTIVE,
        event_time=NOW - timedelta(days=10),
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
        created_at=NOW - timedelta(days=10),
        activated_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(days=1),
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
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW - timedelta(days=10),
        runtime_event_idempotency_key=None,
    )


def _page() -> PageMemory:
    return PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Current title",
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
        created_at=NOW,
        updated_at=NOW,
    )


def _page_version(*, version: int, title: str) -> MemoryPageVersion:
    page = _page()
    return MemoryPageVersion(
        id=f"page_version_{version}",
        page_id=page.id,
        version=version,
        title=title,
        brief=page.brief,
        topics=page.topics,
        open_questions=page.open_questions,
        next_steps=page.next_steps,
        source_event_ids=page.source_event_ids,
        linked_memory_item_ids=page.linked_memory_item_ids,
        changed_by="user",
        change_reason="seed",
        created_at=NOW,
    )


def _graph_link() -> MemoryGraphLink:
    return MemoryGraphLink(
        id="graph_link_001",
        backend="graphiti",
        memory_id="memory_001",
        source_event_id="source_001",
        project_memory_space_id="project_001",
        backend_space_id="project_001",
        backend_object_type="entity_edge",
        backend_object_id="edge_001",
        link_type="fact",
        created_at=NOW,
    )


def _audit_event(audit_id: str, *, entity_id: str) -> AuditEvent:
    return AuditEvent(
        id=audit_id,
        trace_id="trace_audit",
        entity_type="memory_item",
        entity_id=entity_id,
        stage="memory.confirmed",
        input_ref=None,
        output_ref=None,
        decision="confirmed",
        reason_code=None,
        reason_text=None,
        source_event_ids=("source_001",),
        latency_ms=None,
        created_at=NOW,
        actor_id="user_001",
        idempotency_key=None,
        action_ref=None,
        lifecycle_revision=1,
    )


def _forgetting_review(
    *,
    review_id: str = "forgetting_review_001",
    memory_id: str = "memory_001",
    group_id: str = "group_001",
) -> ForgettingReviewCandidate:
    return ForgettingReviewCandidate(
        id=review_id,
        memory_id=memory_id,
        project_memory_space_id="project_001",
        group_id=group_id,
        thread_id="thread_001",
        decayed_score=0.4,
        threshold=DEFAULT_FORGETTING_REVIEW_THRESHOLD,
        reason="score_below_threshold",
        status="pending",
        created_at=NOW,
        updated_at=NOW,
    )


def _push_candidate() -> PushCandidate:
    return PushCandidate(
        id="push_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        type="forgetting_review",
        title="Review Demo scope",
        content="Demo scope needs review.",
        memory_item_ids=("memory_001",),
        source_event_ids=("source_001",),
        trigger_reason="score_below_threshold",
        trigger_source="forgetting_review",
        priority=100,
        expires_at=None,
        status="pending",
        cooldown_key="forgetting_review:memory_001",
        created_at=NOW,
        updated_at=NOW,
    )


def _outbox_job() -> OutboxJob:
    return OutboxJob(
        id="outbox_job_001",
        project_memory_space_id="project_001",
        source_event_id="source_001",
        job_type="memory.decay",
        payload_json={},
        status="pending",
        idempotency_key="outbox:memory.decay:project_001",
        aggregate_key="project_001",
        attempts=0,
        max_attempts=3,
        priority=10,
        next_run_at=NOW,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error=None,
        dead_letter_reason=None,
        created_at=NOW,
        updated_at=NOW,
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
