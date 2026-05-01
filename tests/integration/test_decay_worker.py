from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from memwing.application.decay_service import DecayService
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.models import MemoryDisplayType, MemoryItem, MemoryRoute, MemoryStatus, OutboxJob
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.workers.decay_worker import DECAY_JOB_TYPE, DecayWorker


NOW = datetime(2026, 4, 30, tzinfo=UTC)


def test_decay_worker_updates_scores_and_sends_unpinned_active_memory_to_review() -> None:
    async def scenario() -> None:
        store = InMemoryDataStore()
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item("memory_review", pinned=False))
            await tx.memory_items.upsert(_memory_item("memory_pinned", pinned=True))

        service = DecayService(store, LifecycleTransitionService(store))
        worker = DecayWorker(service)

        result = await worker.run(_decay_job(), now=NOW)

        assert result.scanned_count == 2
        assert result.updated_count == 2
        assert result.review_candidate_count == 1
        assert result.lifecycle_transition_count == 1
        assert len(store.forgetting_review_candidates) == 1
        assert store.forgetting_review_candidates[0].memory_id == "memory_review"

        async with store.transaction() as tx:
            review_item = await tx.memory_items.get("memory_review")
            pinned_item = await tx.memory_items.get("memory_pinned")

        assert review_item is not None
        assert review_item.status is MemoryStatus.NEEDS_REVIEW
        assert review_item.cached_decayed_score == 0.4
        assert review_item.last_decay_computed_at == NOW
        assert pinned_item is not None
        assert pinned_item.status is MemoryStatus.ACTIVE
        assert pinned_item.cached_decayed_score == 0.4

    asyncio.run(scenario())


def _memory_item(memory_id: str, *, pinned: bool) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.VECTOR_ONLY,
        display_type=MemoryDisplayType.NOTE,
        title=f"{memory_id} title",
        content=f"{memory_id} content",
        summary=None,
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
        pinned=pinned,
        created_by="system",
        created_at=NOW - timedelta(days=10),
        activated_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(days=10),
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def _decay_job() -> OutboxJob:
    return OutboxJob(
        id="decay_job_001",
        project_memory_space_id="project_001",
        source_event_id="source_001",
        job_type=DECAY_JOB_TYPE,
        payload_json={"threshold": 0.5},
        status="pending",
        idempotency_key="decay:project_001",
        aggregate_key="project_001",
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
