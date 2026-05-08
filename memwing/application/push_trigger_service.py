from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from memwing.application.push_service import push_candidate_send_job
from memwing.core.models import PushCandidate, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.core.scope_visibility import push_candidate_visible_in_scope
from memwing.ports.event_store import EventStoreUnitOfWorkPort


_TRIGGER_TERMS: Final = frozenset(
    (
        "demo",
        "release",
        "risk",
        "remind",
        "review",
        "launch",
        "演示",
        "发版",
        "发布",
        "风险",
        "提醒",
        "复盘",
        "负责人",
        "计划",
        "项目",
        "决策",
    )
)


@dataclass(frozen=True, slots=True)
class PushTriggerResult:
    triggered: bool
    enqueued_count: int
    candidate_id: str | None = None


class PushTriggerService:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        candidate_limit: int = 20,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._candidate_limit = candidate_limit

    async def trigger_for_source_event(
        self,
        source_event: SourceEvent,
        *,
        now: datetime,
    ) -> PushTriggerResult:
        if not should_trigger_push(source_event.content):
            return PushTriggerResult(triggered=False, enqueued_count=0)

        scope = _scope_from_source_event(source_event)
        async with self._unit_of_work.transaction() as tx:
            candidates = await tx.push_candidates.list_for_project(
                project_memory_space_id=source_event.project_memory_space_id,
                limit=self._candidate_limit,
                sort="priority",
            )
            selected = select_push_candidate(sendable_push_candidates(candidates), scope=scope)
            if selected is None:
                return PushTriggerResult(triggered=True, enqueued_count=0)
            await tx.outbox_jobs.enqueue(
                push_candidate_send_job(
                    selected,
                    now=now,
                    platform="feishu",
                    delivery_source_event_id=source_event.id,
                )
            )
            return PushTriggerResult(
                triggered=True,
                enqueued_count=1,
                candidate_id=selected.id,
            )


def should_trigger_push(content: str) -> bool:
    normalized = content.casefold()
    return any(term in normalized for term in _TRIGGER_TERMS)


def select_push_candidate(
    candidates: tuple[PushCandidate, ...],
    *,
    scope: EffectiveScope,
) -> PushCandidate | None:
    for candidate in candidates:
        if push_candidate_visible_in_scope(candidate, scope):
            return candidate
    return None


def sendable_push_candidates(candidates: tuple[PushCandidate, ...]) -> tuple[PushCandidate, ...]:
    return tuple(candidate for candidate in candidates if candidate.status in {"pending", "approved"})


def _scope_from_source_event(source_event: SourceEvent) -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id=source_event.project_memory_space_id,
        group_ids=(source_event.group_id,) if source_event.group_id is not None else None,
        thread_id=source_event.thread_id,
        shared_group_id=source_event.shared_group_id,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )
