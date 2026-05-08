from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.application.memory_item_ranking import (
    is_current_recallable_memory_item,
    is_history_recallable_memory_item,
    memory_item_blocks_raw_source_fallback,
    memory_item_score,
    rank_current_memory_items,
    rank_memory_items,
    sort_ranked_items,
)
from memwing.core.models import MemoryDisplayType, MemoryItem, MemoryRoute, MemoryStatus


NOW = datetime(2026, 5, 6, tzinfo=UTC)


def test_current_recallable_excludes_hidden_invalid_removed_and_expired_items() -> None:
    active = _memory_item("memory_active", MemoryStatus.ACTIVE)

    assert is_current_recallable_memory_item(active)
    assert not is_current_recallable_memory_item(replace(active, status=MemoryStatus.INVALID))
    assert not is_current_recallable_memory_item(replace(active, status=MemoryStatus.HIDDEN))
    assert not is_current_recallable_memory_item(replace(active, status=MemoryStatus.REMOVED))
    assert not is_current_recallable_memory_item(replace(active, valid_to=NOW))


def test_raw_source_fallback_blocking_keeps_reviewable_items_from_bypassing_gate() -> None:
    active = _memory_item("memory_active", MemoryStatus.ACTIVE)

    assert memory_item_blocks_raw_source_fallback(
        replace(active, status=MemoryStatus.NEEDS_REVIEW)
    )
    assert memory_item_blocks_raw_source_fallback(
        replace(active, status=MemoryStatus.CANDIDATE)
    )
    assert not memory_item_blocks_raw_source_fallback(
        replace(active, status=MemoryStatus.INVALID, invalidated_at=NOW)
    )
    assert not memory_item_blocks_raw_source_fallback(
        replace(active, status=MemoryStatus.HIDDEN, hidden_at=NOW)
    )
    assert not memory_item_blocks_raw_source_fallback(replace(active, valid_to=NOW))


def test_history_recallable_keeps_non_removed_historical_states() -> None:
    assert is_history_recallable_memory_item(_memory_item("memory_archived", MemoryStatus.ARCHIVED))
    assert is_history_recallable_memory_item(_memory_item("memory_invalid", MemoryStatus.INVALID))
    assert not is_history_recallable_memory_item(_memory_item("memory_hidden", MemoryStatus.HIDDEN))
    assert not is_history_recallable_memory_item(
        replace(_memory_item("memory_removed", MemoryStatus.ACTIVE), removed_at=NOW)
    )


def test_current_ranking_adds_query_relevance_and_filters_misses() -> None:
    deadline = replace(
        _memory_item("memory_deadline", MemoryStatus.ACTIVE),
        title="上线截止时间",
        content="云帆项目上线截止时间是 5 月 20 日。",
        original_score=0.6,
    )
    owner = replace(
        _memory_item("memory_owner", MemoryStatus.ACTIVE),
        title="项目负责人",
        content="云帆项目负责人是沈南。",
        original_score=0.9,
    )

    ranked = rank_current_memory_items(
        query="上线截止时间",
        items=(owner, deadline),
        min_score=0.0,
        now=NOW,
    )

    assert tuple(item.id for item, _score in ranked) == ("memory_deadline",)


def test_history_ranking_retains_query_misses_with_penalty_and_sort_modes() -> None:
    older = replace(
        _memory_item("memory_old", MemoryStatus.ARCHIVED),
        content="旧方案讨论记录。",
        event_time=NOW - timedelta(days=2),
        updated_at=NOW - timedelta(days=2),
        original_score=0.9,
    )
    newer = replace(
        _memory_item("memory_new", MemoryStatus.ACTIVE),
        content="当前方案上线窗口。",
        event_time=NOW,
        updated_at=NOW,
        original_score=0.6,
    )

    ranked = rank_memory_items(
        query="上线",
        items=(older, newer),
        mode="history",
        min_score=0.0,
        now=NOW,
    )

    assert {item.id for item, _score in ranked} == {"memory_old", "memory_new"}
    assert dict((item.id, score) for item, score in ranked)["memory_old"] < 0.9
    assert tuple(item.id for item, _score in sort_ranked_items(ranked, sort="event_time")) == (
        "memory_new",
        "memory_old",
    )


def test_memory_item_score_prefers_cached_decayed_score() -> None:
    item = replace(_memory_item("memory_cached", MemoryStatus.ACTIVE), cached_decayed_score=0.42)

    assert memory_item_score(item, now=NOW) == 0.42


def _memory_item(memory_id: str, status: MemoryStatus) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.RAW_ONLY,
        display_type=MemoryDisplayType.NOTE,
        title=memory_id,
        content=memory_id,
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=status,
        event_time=NOW,
        valid_from=NOW,
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
        activated_at=NOW if status is MemoryStatus.ACTIVE else None,
        updated_at=NOW,
        archived_at=NOW if status is MemoryStatus.ARCHIVED else None,
        hidden_at=NOW if status is MemoryStatus.HIDDEN else None,
        invalidated_at=NOW if status is MemoryStatus.INVALID else None,
        removed_at=NOW if status is MemoryStatus.REMOVED else None,
    )
