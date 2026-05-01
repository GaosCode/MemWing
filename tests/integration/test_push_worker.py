from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from memwing.application.decay_service import DEFAULT_FORGETTING_REVIEW_THRESHOLD
from memwing.application.push_service import PushService
from memwing.core.models import (
    ForgettingReviewCandidate,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.workers.push_worker import PushWorker


NOW = datetime(2026, 4, 30, tzinfo=UTC)
SCOPE = EffectiveScope(
    project_memory_space_id="project_001",
    group_ids=("group_001",),
    thread_id="thread_001",
    shared_group_id=None,
    safe_mode_enabled=True,
    cross_group_allowed=False,
)


def test_push_worker_generates_only_stable_source_candidate_types() -> None:
    store = InMemoryDataStore()
    worker = PushWorker(PushService(store, now=lambda: NOW))

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item("memory_review", MemoryDisplayType.NOTE))
            await tx.memory_items.upsert(_memory_item("memory_decision", MemoryDisplayType.DECISION))
            await tx.memory_items.upsert(
                _memory_item(
                    "memory_other_scope",
                    MemoryDisplayType.NOTE,
                    group_id="group_other",
                    thread_id="thread_other",
                )
            )
            await tx.forgetting_review_candidates.upsert(_forgetting_review("memory_review"))
            await tx.forgetting_review_candidates.upsert(_forgetting_review("memory_other_scope"))

        result = await worker.generate_candidates(scope=SCOPE, trace_id="trace_push_worker")

        assert result.forgetting_review_count == 1
        assert result.decision_card_count == 1
        generated_types = {candidate.type for candidate in store.push_candidates}
        assert generated_types == {"forgetting_review", "decision_card"}
        assert "conflict" not in generated_types
        assert "deadline" not in generated_types
        assert "daily_digest" not in generated_types

    asyncio.run(scenario())


def _memory_item(
    memory_id: str,
    display_type: MemoryDisplayType,
    *,
    group_id: str = "group_001",
    thread_id: str = "thread_001",
) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=display_type,
        title=f"Title {memory_id}",
        content=f"Content {memory_id}",
        summary=f"Summary {memory_id}",
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
        created_at=NOW - timedelta(days=1),
        activated_at=NOW - timedelta(days=1),
        updated_at=NOW,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def _forgetting_review(memory_id: str) -> ForgettingReviewCandidate:
    return ForgettingReviewCandidate(
        id=f"forgetting_review_{memory_id}",
        memory_id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        decayed_score=0.4,
        threshold=DEFAULT_FORGETTING_REVIEW_THRESHOLD,
        reason="score_below_threshold",
        status="pending",
        created_at=NOW,
        updated_at=NOW,
    )
