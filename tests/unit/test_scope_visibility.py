from dataclasses import replace
from datetime import UTC, datetime

from memwing.core.models import (
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    PageMemory,
    PushCandidate,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.core.scope_visibility import (
    memory_item_visible_in_scope,
    page_memory_visible_in_scope,
    push_candidate_visible_in_scope,
    scope_values_visible_in_scope,
    source_event_visible_in_scope,
)


NOW = datetime(2026, 5, 6, tzinfo=UTC)


def test_scope_values_visible_in_scope_allows_project_wide_group_visibility() -> None:
    assert scope_values_visible_in_scope(
        group_id="group_002",
        thread_id="thread_002",
        shared_group_id=None,
        effective_scope=_scope(group_ids=None, thread_id=None),
    )


def test_scope_values_visible_in_scope_applies_group_thread_and_shared_narrowing() -> None:
    scope = _scope(
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id="shared_001",
    )

    assert scope_values_visible_in_scope(
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id="shared_001",
        effective_scope=scope,
    )
    assert not scope_values_visible_in_scope(
        group_id="group_002",
        thread_id="thread_001",
        shared_group_id="shared_001",
        effective_scope=scope,
    )
    assert not scope_values_visible_in_scope(
        group_id="group_001",
        thread_id="thread_002",
        shared_group_id="shared_001",
        effective_scope=scope,
    )
    assert not scope_values_visible_in_scope(
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id="shared_002",
        effective_scope=scope,
    )


def test_object_visibility_checks_project_memory_space() -> None:
    scope = _scope()

    assert source_event_visible_in_scope(_source_event(), scope)
    assert memory_item_visible_in_scope(_memory_item(), scope)
    assert page_memory_visible_in_scope(_page_memory(), scope)
    assert push_candidate_visible_in_scope(_push_candidate(), scope)

    assert not source_event_visible_in_scope(
        replace(_source_event(), project_memory_space_id="other_project"),
        scope,
    )
    assert not memory_item_visible_in_scope(
        replace(_memory_item(), project_memory_space_id="other_project"),
        scope,
    )
    assert not page_memory_visible_in_scope(
        replace(_page_memory(), project_memory_space_id="other_project"),
        scope,
    )
    assert not push_candidate_visible_in_scope(
        replace(_push_candidate(), project_memory_space_id="other_project"),
        scope,
    )


def test_memory_visibility_is_independent_from_lifecycle_and_redaction() -> None:
    scope = _scope()

    assert memory_item_visible_in_scope(
        replace(
            _memory_item(),
            status=MemoryStatus.HIDDEN,
            hidden_at=NOW,
            invalidated_at=NOW,
            removed_at=NOW,
            valid_to=NOW,
        ),
        scope,
    )
    assert source_event_visible_in_scope(
        replace(
            _source_event(),
            purged_at=NOW,
            purge_level="memwing_redaction",
        ),
        scope,
    )


def _scope(
    *,
    group_ids: tuple[str, ...] | None = ("group_001",),
    thread_id: str | None = "thread_001",
    shared_group_id: str | None = None,
) -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=group_ids,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
        safe_mode_enabled=group_ids is not None,
        cross_group_allowed=group_ids is None,
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
        source_type="text",
        content="Decision",
        content_preview="Decision",
        source_url=None,
        event_time=NOW,
        raw_payload_hash="hash",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
    )


def _memory_item() -> MemoryItem:
    return MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.RAW_ONLY,
        display_type=MemoryDisplayType.NOTE,
        title="Decision",
        content="Decision",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.ACTIVE,
        event_time=NOW,
        valid_from=NOW,
        valid_to=None,
        original_score=0.9,
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


def _page_memory() -> PageMemory:
    return PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Thread",
        brief="Thread brief",
        topics=(),
        open_questions=(),
        next_steps=(),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
        version=1,
        needs_rebuild=False,
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
        type="decision_card",
        title="Decision",
        content="Decision",
        memory_item_ids=("memory_001",),
        source_event_ids=("source_001",),
        trigger_reason="decision_card",
        trigger_source="memory_item",
        priority=80,
        expires_at=None,
        status="pending",
        cooldown_key="decision_card:memory_001",
        created_at=NOW,
        updated_at=NOW,
    )
