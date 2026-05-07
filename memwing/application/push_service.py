from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable
import uuid

from memwing.core.models import MemoryDisplayType, MemoryItem, MemoryStatus, OutboxJob, PushCandidate
from memwing.core.scope import EffectiveScope, effective_scope_matches
from memwing.ports.event_store import EventStoreUnitOfWorkPort


@dataclass(frozen=True, slots=True)
class PushGenerationResult:
    generated_count: int
    push_candidate_ids: tuple[str, ...]
    trace_id: str


class PushService:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._now = now or (lambda: datetime.now(UTC))

    async def generate_forgetting_review(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> PushGenerationResult:
        now = self._now()
        generated: list[str] = []
        async with self._unit_of_work.transaction() as tx:
            reviews = await tx.forgetting_review_candidates.list_pending(
                project_memory_space_id=scope.project_memory_space_id,
                limit=limit,
            )
            for review in reviews:
                item = await tx.memory_items.get(review.memory_id)
                if item is None or item.status is MemoryStatus.REMOVED or not _item_in_scope(item, scope):
                    continue
                candidate = _forgetting_review_candidate(item, review.reason, now)
                candidate = await tx.push_candidates.upsert(candidate)
                generated.append(candidate.id)
        return PushGenerationResult(
            generated_count=len(generated),
            push_candidate_ids=tuple(generated),
            trace_id=trace_id,
        )

    async def generate_decision_cards(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> PushGenerationResult:
        now = self._now()
        generated: list[str] = []
        async with self._unit_of_work.transaction() as tx:
            items = await tx.memory_items.list_for_scope(scope=scope, limit=limit)
            for item in items:
                if item.display_type is not MemoryDisplayType.DECISION:
                    continue
                if item.status is not MemoryStatus.ACTIVE:
                    continue
                candidate = decision_card_candidate(item, now)
                candidate = await tx.push_candidates.upsert(candidate)
                generated.append(candidate.id)
        return PushGenerationResult(
            generated_count=len(generated),
            push_candidate_ids=tuple(generated),
            trace_id=trace_id,
        )


def _item_in_scope(item: MemoryItem, scope: EffectiveScope) -> bool:
    return item.project_memory_space_id == scope.project_memory_space_id and effective_scope_matches(
        group_id=item.group_id,
        thread_id=item.thread_id,
        shared_group_id=item.shared_group_id,
        scope=scope,
    )


def _forgetting_review_candidate(item: MemoryItem, reason: str, now: datetime) -> PushCandidate:
    return PushCandidate(
        id=_uuid("push", "forgetting_review", item.id),
        project_memory_space_id=item.project_memory_space_id,
        group_id=item.group_id,
        thread_id=item.thread_id,
        shared_group_id=item.shared_group_id,
        type="forgetting_review",
        title=f"Review {item.title}",
        content=item.summary or item.content,
        memory_item_ids=(item.id,),
        source_event_ids=item.source_event_ids,
        trigger_reason=reason,
        trigger_source="forgetting_review",
        priority=100,
        expires_at=None,
        status="pending",
        cooldown_key=f"forgetting_review:{item.id}",
        created_at=now,
        updated_at=now,
    )


def decision_card_candidate(item: MemoryItem, now: datetime) -> PushCandidate:
    return PushCandidate(
        id=_uuid("push", "decision_card", item.id),
        project_memory_space_id=item.project_memory_space_id,
        group_id=item.group_id,
        thread_id=item.thread_id,
        shared_group_id=item.shared_group_id,
        type="decision_card",
        title=item.title,
        content=item.content or item.summary or item.title,
        memory_item_ids=(item.id,),
        source_event_ids=item.source_event_ids,
        trigger_reason="decision_card",
        trigger_source="memory_item",
        priority=80,
        expires_at=None,
        status="pending",
        cooldown_key=f"decision_card:{item.id}",
        created_at=now,
        updated_at=now,
    )


def push_candidate_send_job(
    candidate: PushCandidate,
    *,
    now: datetime,
    platform: str = "feishu",
    delivery_source_event_id: str | None = None,
) -> OutboxJob:
    source_event_id = delivery_source_event_id or (
        candidate.source_event_ids[0] if candidate.source_event_ids else None
    )
    if source_event_id is None:
        raise ValueError("push candidate send job requires a source event id")
    delivery_key = delivery_source_event_id or "candidate_source"
    idempotency_key = f"push_candidate.send:{candidate.id}:{platform}:{delivery_key}"
    payload_json: dict[str, object] = {"push_candidate_id": candidate.id, "platform": platform}
    if delivery_source_event_id is not None:
        payload_json["delivery_source_event_id"] = delivery_source_event_id
    return OutboxJob(
        id=_uuid("outbox", idempotency_key),
        project_memory_space_id=candidate.project_memory_space_id,
        source_event_id=source_event_id,
        job_type="push_candidate.send",
        payload_json=payload_json,
        status="pending",
        idempotency_key=idempotency_key,
        aggregate_key=f"push_candidate.send:{candidate.id}",
        attempts=0,
        max_attempts=3,
        priority=90,
        next_run_at=now,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error=None,
        dead_letter_reason=None,
        created_at=now,
        updated_at=now,
    )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
