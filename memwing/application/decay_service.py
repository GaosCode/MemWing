from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
import uuid

from memwing.core.forgetting_curve import (
    compute_decayed_score,
    effective_last_touched_at,
    should_enter_forgetting_review,
)
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import ForgettingReviewCandidate, MemoryItem, MemoryStatus
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.lifecycle_transition import (
    LifecycleTransitionPort,
    LifecycleTransitionRequest,
)


DEFAULT_FORGETTING_REVIEW_THRESHOLD: Final = 0.5
DEFAULT_DECAY_CANDIDATE_LIMIT: Final = 100


@dataclass(frozen=True, slots=True)
class DecayProcessCommand:
    project_memory_space_id: str
    now: datetime
    threshold: float = DEFAULT_FORGETTING_REVIEW_THRESHOLD
    limit: int = DEFAULT_DECAY_CANDIDATE_LIMIT
    actor_id: str = "system"
    trace_id: str = "memory_decay:process"


@dataclass(frozen=True, slots=True)
class DecayProcessResult:
    scanned_count: int
    updated_count: int
    review_candidate_count: int
    lifecycle_transition_count: int


class DecayService:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        lifecycle_transitions: LifecycleTransitionPort,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._lifecycle_transitions = lifecycle_transitions

    async def process_project(self, command: DecayProcessCommand) -> DecayProcessResult:
        async with self._unit_of_work.transaction() as tx:
            candidates = await tx.memory_items.list_decay_candidates(
                project_memory_space_id=command.project_memory_space_id,
                limit=command.limit,
            )

        updated_count = 0
        review_candidate_count = 0
        lifecycle_transition_count = 0
        for item in candidates:
            decayed_score = compute_decayed_score(
                original_score=item.original_score,
                effective_last_touched_at=effective_last_touched_at(item),
                now=command.now,
                half_life_days=item.half_life_days,
            )
            updated_item = replace(
                item,
                cached_decayed_score=decayed_score,
                last_decay_computed_at=command.now,
                updated_at=command.now,
            )
            async with self._unit_of_work.transaction() as tx:
                saved_item = await tx.memory_items.upsert(updated_item)
            updated_count += 1

            if should_enter_forgetting_review(
                decayed_score=decayed_score,
                threshold=command.threshold,
                pinned=saved_item.pinned,
            ):
                async with self._unit_of_work.transaction() as tx:
                    await tx.forgetting_review_candidates.upsert(
                        _forgetting_review_candidate(
                            item=saved_item,
                            decayed_score=decayed_score,
                            threshold=command.threshold,
                            now=command.now,
                        )
                    )
                review_candidate_count += 1
                if saved_item.status in (MemoryStatus.ACTIVE, MemoryStatus.FADING):
                    await self._lifecycle_transitions.transition(
                        LifecycleTransitionRequest(
                            memory_id=saved_item.id,
                            action=LifecycleAction.MARK_NEEDS_REVIEW,
                            actor_id=command.actor_id,
                            reason="decayed_score_below_forgetting_review_threshold",
                            idempotency_key=_transition_idempotency_key(
                                saved_item.id,
                                command.threshold,
                            ),
                            trace_id=command.trace_id,
                            now=command.now,
                        )
                    )
                    lifecycle_transition_count += 1

        return DecayProcessResult(
            scanned_count=len(candidates),
            updated_count=updated_count,
            review_candidate_count=review_candidate_count,
            lifecycle_transition_count=lifecycle_transition_count,
        )


def _forgetting_review_candidate(
    *,
    item: MemoryItem,
    decayed_score: float,
    threshold: float,
    now: datetime,
) -> ForgettingReviewCandidate:
    return ForgettingReviewCandidate(
        id=_uuid("forgetting_review", item.id, str(threshold)),
        memory_id=item.id,
        project_memory_space_id=item.project_memory_space_id,
        group_id=item.group_id,
        thread_id=item.thread_id,
        decayed_score=decayed_score,
        threshold=threshold,
        reason="score_below_threshold",
        status="pending",
        created_at=now,
        updated_at=now,
    )


def _transition_idempotency_key(memory_id: str, threshold: float) -> str:
    return f"memory_decay:mark_needs_review:{memory_id}:{threshold}"


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
