from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
import uuid

from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import (
    AuditEvent,
    GraphWriteJob,
    LongTermFilterItem,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    PageMemoryScopeType,
    SourceEvent,
    graph_write_serialization_key,
)
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.lifecycle_transition import (
    LifecycleTransitionPort,
    LifecycleTransitionRequest,
)
from memwing.ports.llm_filter import LongTermFilterPort, LongTermFilterRequest


_SYSTEM_ACTOR: Final = "system"
_HISTORY_ITEM_LIMIT: Final = 50
_AUTO_ACTIVATE_ROUTES: Final = frozenset((MemoryRoute.GRAPH, MemoryRoute.VECTOR_ONLY))
_AUTO_ACTIVATE_MIN_SCORE: Final = 0.75


@dataclass(frozen=True, slots=True)
class LongTermFilterProcessCommand:
    scope: EffectiveScope
    source_event_ids: tuple[str, ...]
    now: datetime
    trace_id: str = "long_term_filter:process"
    actor_id: str | None = _SYSTEM_ACTOR


@dataclass(frozen=True, slots=True)
class LongTermFilterProcessResult:
    source_event_count: int
    candidate_count: int
    activated_count: int
    graph_write_job_count: int


class LongTermFilterService:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        filter_port: LongTermFilterPort,
        *,
        lifecycle_transition: LifecycleTransitionPort,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._filter_port = filter_port
        self._lifecycle_transition = lifecycle_transition

    async def process_scope(
        self,
        command: LongTermFilterProcessCommand,
    ) -> LongTermFilterProcessResult:
        async with self._unit_of_work.transaction() as tx:
            source_events = await _load_source_events(
                tx.source_events,
                source_event_ids=command.source_event_ids,
                scope=command.scope,
            )
            history_items = await tx.memory_items.list_for_scope(
                scope=command.scope,
                limit=_HISTORY_ITEM_LIMIT,
            )
            scope_type, scope_id = _page_scope_ref(command.scope)
            recent_page_memory = await tx.memory_pages.get_by_scope(
                project_memory_space_id=command.scope.project_memory_space_id,
                scope_type=scope_type,
                scope_id=scope_id,
            )

        if not source_events:
            await self._record_audit(
                command=command,
                stage="long_term_filter.skipped",
                decision="no_source_events",
                source_event_ids=(),
            )
            return LongTermFilterProcessResult(
                source_event_count=0,
                candidate_count=0,
                activated_count=0,
                graph_write_job_count=0,
            )

        filter_items = await self._filter_port.filter_events(
            LongTermFilterRequest(
                scope=command.scope,
                source_events=source_events,
                recent_page_memory=recent_page_memory,
                history_items=history_items,
                evidence_snippets=(),
                trace_id=command.trace_id,
            )
        )
        _validate_filter_items(filter_items, source_event_ids={event.id for event in source_events})

        graph_write_job_count = 0
        saved_items: list[MemoryItem] = []
        async with self._unit_of_work.transaction() as tx:
            for filter_item in filter_items:
                memory_item = _memory_item_from_filter_item(
                    filter_item=filter_item,
                    scope=command.scope,
                    now=command.now,
                )
                existing_item = await tx.memory_items.get_for_update(memory_item.id)
                saved_item = existing_item or await tx.memory_items.upsert(memory_item)
                saved_items.append(saved_item)
                if saved_item.route == MemoryRoute.GRAPH:
                    await tx.graph_write_jobs.enqueue(
                        _graph_write_job_from_memory_item(saved_item, now=command.now)
                    )
                    graph_write_job_count += 1

        activated_count = 0
        for item in saved_items:
            if not _should_auto_activate(item):
                continue
            await self._lifecycle_transition.transition(
                LifecycleTransitionRequest(
                    memory_id=item.id,
                    action=LifecycleAction.APPROVE,
                    actor_id=command.actor_id or _SYSTEM_ACTOR,
                    reason="auto-approved by long term filter",
                    idempotency_key=f"long_term_filter:auto_approve:{command.trace_id}:{item.id}",
                    trace_id=command.trace_id,
                    now=command.now,
                )
            )
            activated_count += 1

        async with self._unit_of_work.transaction() as tx:
            await tx.audit_events.record(
                _audit_event(
                    command=command,
                    stage="long_term_filter.succeeded",
                    decision=(
                        f"created_candidates:{len(filter_items)};"
                        f"auto_activated:{activated_count}"
                    ),
                    source_event_ids=tuple(event.id for event in source_events),
                )
            )

        return LongTermFilterProcessResult(
            source_event_count=len(source_events),
            candidate_count=len(filter_items),
            activated_count=activated_count,
            graph_write_job_count=graph_write_job_count,
        )

    async def _record_audit(
        self,
        *,
        command: LongTermFilterProcessCommand,
        stage: str,
        decision: str,
        source_event_ids: tuple[str, ...],
    ) -> None:
        async with self._unit_of_work.transaction() as tx:
            await tx.audit_events.record(
                _audit_event(
                    command=command,
                    stage=stage,
                    decision=decision,
                    source_event_ids=source_event_ids,
                )
            )


def _page_scope_ref(scope: EffectiveScope) -> tuple[PageMemoryScopeType, str]:
    if scope.thread_id is not None:
        return "thread", scope.thread_id
    if scope.group_ids is not None and len(scope.group_ids) == 1:
        return "group", scope.group_ids[0]
    return "project", scope.project_memory_space_id


async def _load_source_events(
    repository: object,
    *,
    source_event_ids: tuple[str, ...],
    scope: EffectiveScope,
) -> tuple[SourceEvent, ...]:
    source_events: list[SourceEvent] = []
    missing_ids: list[str] = []
    for source_event_id in source_event_ids:
        event = await repository.get_source_event(source_event_id)
        if event is None or not _source_event_in_scope(event, scope):
            missing_ids.append(source_event_id)
            continue
        source_events.append(event)
    if missing_ids:
        raise ValueError("long term filter source_event_ids are missing or outside scope")
    return tuple(source_events)


def _source_event_in_scope(event: SourceEvent, scope: EffectiveScope) -> bool:
    if event.project_memory_space_id != scope.project_memory_space_id:
        return False
    if scope.thread_id is not None and event.thread_id != scope.thread_id:
        return False
    if scope.group_ids is not None and event.group_id not in scope.group_ids:
        return False
    if scope.shared_group_id is not None and event.shared_group_id != scope.shared_group_id:
        return False
    return True


def _validate_filter_items(
    items: tuple[LongTermFilterItem, ...],
    *,
    source_event_ids: set[str],
) -> None:
    for item in items:
        unknown_ids = set(item.source_event_ids) - source_event_ids
        if unknown_ids:
            raise ValueError(
                "long term filter returned source_event_ids outside the loaded scope"
            )
        if item.primary_source_event_id is not None and item.primary_source_event_id not in source_event_ids:
            raise ValueError(
                "long term filter returned primary_source_event_id outside the loaded scope"
            )


def _should_auto_activate(item: MemoryItem) -> bool:
    return (
        item.status is MemoryStatus.CANDIDATE
        and item.route in _AUTO_ACTIVATE_ROUTES
        and item.original_score >= _AUTO_ACTIVATE_MIN_SCORE
    )


def _memory_item_from_filter_item(
    *,
    filter_item: LongTermFilterItem,
    scope: EffectiveScope,
    now: datetime,
) -> MemoryItem:
    group_id = scope.group_ids[0] if scope.group_ids and len(scope.group_ids) == 1 else None
    return MemoryItem(
        id=_uuid("memory_item", filter_item.title, *filter_item.source_event_ids),
        project_memory_space_id=scope.project_memory_space_id,
        group_id=group_id,
        thread_id=scope.thread_id,
        shared_group_id=scope.shared_group_id,
        route=filter_item.route,
        display_type=filter_item.display_type,
        title=filter_item.title,
        content=filter_item.content,
        summary=filter_item.reason,
        source_event_ids=filter_item.source_event_ids,
        primary_source_event_id=filter_item.primary_source_event_id,
        status=MemoryStatus.CANDIDATE,
        event_time=filter_item.event_time,
        valid_from=filter_item.valid_from,
        valid_to=filter_item.valid_to,
        original_score=filter_item.original_score,
        half_life_days=filter_item.half_life_days,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=now,
        activated_at=None,
        updated_at=now,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def _graph_write_job_from_memory_item(item: MemoryItem, *, now: datetime) -> GraphWriteJob:
    return GraphWriteJob(
        id=_uuid("graph_write_job", item.id),
        backend="graphiti",
        serialization_key=graph_write_serialization_key(
            backend="graphiti",
            project_memory_space_id=item.project_memory_space_id,
        ),
        project_memory_space_id=item.project_memory_space_id,
        thread_id=item.thread_id,
        saga_id=None,
        memory_id=item.id,
        source_event_ids=item.source_event_ids,
        route=item.route,
        status="pending",
        idempotency_key=f"graph:{item.id}",
        attempts=0,
        max_attempts=3,
        priority=100,
        next_run_at=now,
        dead_letter_reason=None,
        last_error=None,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        created_at=now,
        updated_at=now,
    )


def _audit_event(
    *,
    command: LongTermFilterProcessCommand,
    stage: str,
    decision: str,
    source_event_ids: tuple[str, ...],
) -> AuditEvent:
    idempotency_key = f"{stage}:{command.scope.project_memory_space_id}:{command.trace_id}"
    return AuditEvent(
        id=_uuid("audit", idempotency_key),
        trace_id=command.trace_id,
        entity_type="long_term_filter",
        entity_id=command.scope.project_memory_space_id,
        stage=stage,
        input_ref=None,
        output_ref=None,
        decision=decision,
        reason_code=None,
        reason_text=None,
        source_event_ids=source_event_ids,
        latency_ms=None,
        created_at=command.now,
        actor_id=command.actor_id,
        idempotency_key=idempotency_key,
        action_ref=None,
        lifecycle_revision=None,
    )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
