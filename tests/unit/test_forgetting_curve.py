from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from memwing.core.forgetting_curve import (
    compute_decayed_score,
    effective_last_touched_at,
    should_enter_forgetting_review,
)
from memwing.core.models import MemoryDisplayType, MemoryItem, MemoryRoute, MemoryStatus


NOW = datetime(2026, 4, 30, tzinfo=UTC)


def test_forgetting_curve_halves_original_score_after_one_half_life() -> None:
    score = compute_decayed_score(
        original_score=0.8,
        effective_last_touched_at=NOW - timedelta(days=10),
        now=NOW,
        half_life_days=10,
    )

    assert score == pytest.approx(0.4)


def test_forgetting_curve_does_not_penalize_future_last_touched_time() -> None:
    score = compute_decayed_score(
        original_score=0.8,
        effective_last_touched_at=NOW + timedelta(days=1),
        now=NOW,
        half_life_days=10,
    )

    assert score == pytest.approx(0.8)


def test_forgetting_review_threshold_ignores_pinned_memories() -> None:
    assert should_enter_forgetting_review(
        decayed_score=0.49,
        threshold=0.5,
        pinned=False,
    )
    assert not should_enter_forgetting_review(
        decayed_score=0.49,
        threshold=0.5,
        pinned=True,
    )


def test_effective_last_touched_prefers_confirmed_then_reviewed_then_activated() -> None:
    item = _memory_item()

    assert effective_last_touched_at(item) == NOW - timedelta(days=30)
    assert effective_last_touched_at(
        replace(item, activated_at=NOW - timedelta(days=20))
    ) == NOW - timedelta(days=20)
    assert effective_last_touched_at(
        replace(
            item,
            activated_at=NOW - timedelta(days=20),
            last_reviewed_at=NOW - timedelta(days=10),
        )
    ) == NOW - timedelta(days=10)
    assert effective_last_touched_at(
        replace(
            item,
            activated_at=NOW - timedelta(days=20),
            last_reviewed_at=NOW - timedelta(days=10),
            last_confirmed_at=NOW - timedelta(days=5),
        )
    ) == NOW - timedelta(days=5)


def _memory_item() -> MemoryItem:
    return MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id=None,
        thread_id=None,
        shared_group_id=None,
        route=MemoryRoute.VECTOR_ONLY,
        display_type=MemoryDisplayType.NOTE,
        title="Retention rule",
        content="Keep project memory access stable.",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.ACTIVE,
        event_time=NOW,
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
        created_at=NOW - timedelta(days=30),
        activated_at=None,
        updated_at=NOW - timedelta(days=30),
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )
