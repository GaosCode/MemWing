from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Final
import uuid

from memwing.core.errors import DomainRuleViolation
from memwing.core.lifecycle import LifecycleAction, transition_status
from memwing.core.models import AuditEvent, MemoryItem, MemoryStatus, MemoryVersion
from memwing.ports.event_store import EventStoreUnitOfWorkPort, MemoryVersionRepositoryPort
from memwing.ports.lifecycle_transition import (
    LifecycleTransitionRequest,
    LifecycleTransitionResult,
)


_ENTITY_TYPE: Final = "memory_item"
_SUCCESS_STAGE: Final = "lifecycle_transition.succeeded"
_FAILURE_STAGE: Final = "lifecycle_transition.failed"
_PIN_ACTIONS: Final = frozenset((LifecycleAction.PIN, LifecycleAction.UNPIN))


class LifecycleTransitionService:
    def __init__(self, unit_of_work: EventStoreUnitOfWorkPort) -> None:
        self._unit_of_work = unit_of_work

    async def transition(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransitionResult:
        failure_reason: str | None = None
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type=_ENTITY_TYPE,
                entity_id=request.memory_id,
                idempotency_key=request.idempotency_key,
            )
            if existing_audit is not None:
                if existing_audit.stage == _FAILURE_STAGE:
                    if existing_audit.reason_text is None:
                        raise DomainRuleViolation(
                            "lifecycle failure audit does not include reason_text"
                        )
                    raise DomainRuleViolation(existing_audit.reason_text)
                replay_action = _successful_audit_action(existing_audit)
                if replay_action != request.action:
                    raise DomainRuleViolation(
                        "idempotency key was already used for "
                        f"{replay_action.value}; cannot replay {request.action.value}"
                    )
                memory_item = await tx.memory_items.get(request.memory_id)
                if memory_item is None:
                    raise DomainRuleViolation(f"memory item {request.memory_id} was not found")
                _ensure_replay_matches_current_memory(
                    audit_event=existing_audit,
                    action=replay_action,
                    memory_item=memory_item,
                )
                return LifecycleTransitionResult(
                    memory_item=memory_item,
                    previous_status=_status_from_audit_input(existing_audit),
                    audit_event=existing_audit,
                )

            memory_item = await tx.memory_items.get(request.memory_id)
            if memory_item is None:
                audit_event = _audit_event(
                    request=request,
                    stage=_FAILURE_STAGE,
                    input_ref=None,
                    output_ref=None,
                    decision="rejected",
                    reason_code="memory_item_not_found",
                    reason_text=f"memory item {request.memory_id} was not found",
                    source_event_ids=(),
                )
                await tx.audit_events.record(audit_event)
                failure_reason = audit_event.reason_text
            else:
                previous_status = memory_item.status
                try:
                    next_status = transition_status(previous_status, request.action)
                except DomainRuleViolation as exc:
                    audit_event = _audit_event(
                        request=request,
                        stage=_FAILURE_STAGE,
                        input_ref=previous_status.value,
                        output_ref=None,
                        decision="rejected",
                        reason_code="invalid_lifecycle_transition",
                        reason_text=str(exc),
                        source_event_ids=memory_item.source_event_ids,
                    )
                    await tx.audit_events.record(audit_event)
                    failure_reason = str(exc)
                else:
                    updated_item = _transitioned_memory_item(
                        memory_item,
                        action=request.action,
                        next_status=next_status,
                        now=request.now,
                    )
                    saved_item = await tx.memory_items.upsert(updated_item)
                    if request.action not in _PIN_ACTIONS:
                        await tx.memory_versions.record(
                            _memory_version(
                                item=saved_item,
                                request=request,
                                version=await _next_memory_version(
                                    tx.memory_versions,
                                    memory_item.id,
                                ),
                            )
                        )
                    audit_event = _audit_event(
                        request=request,
                        stage=_SUCCESS_STAGE,
                        input_ref=previous_status.value,
                        output_ref=_output_ref(request.action, saved_item),
                        decision=request.action.value,
                        reason_code=None,
                        reason_text=request.reason,
                        source_event_ids=saved_item.source_event_ids,
                    )
                    audit_event = await tx.audit_events.record(audit_event)
                    return LifecycleTransitionResult(
                        memory_item=saved_item,
                        previous_status=previous_status,
                        audit_event=audit_event,
                    )

        if failure_reason is None:
            raise RuntimeError("lifecycle transition did not produce a result or failure")
        raise DomainRuleViolation(failure_reason)


def _transitioned_memory_item(
    item: MemoryItem,
    *,
    action: LifecycleAction,
    next_status: MemoryStatus,
    now: datetime,
) -> MemoryItem:
    updates: dict[str, object] = {"status": next_status, "updated_at": now}
    if action is LifecycleAction.APPROVE or (
        next_status is MemoryStatus.ACTIVE
        and item.status is not MemoryStatus.ACTIVE
        and action
        in (
            LifecycleAction.CONFIRM,
            LifecycleAction.REVIEW,
            LifecycleAction.UNARCHIVE,
            LifecycleAction.UNHIDE,
        )
    ):
        updates["activated_at"] = now
    if action is LifecycleAction.ARCHIVE:
        updates["archived_at"] = now
    elif action is LifecycleAction.HIDE:
        updates["hidden_at"] = now
    elif action is LifecycleAction.INVALIDATE:
        updates["invalidated_at"] = now
    elif action is LifecycleAction.REMOVE:
        updates["removed_at"] = now
    elif action is LifecycleAction.REVIEW:
        updates["last_reviewed_at"] = now
    elif action is LifecycleAction.CONFIRM:
        updates["last_confirmed_at"] = now
    elif action is LifecycleAction.PIN:
        updates["pinned"] = True
    elif action is LifecycleAction.UNPIN:
        updates["pinned"] = False
    return replace(item, **updates)


async def _next_memory_version(
    memory_versions: MemoryVersionRepositoryPort,
    memory_id: str,
) -> int:
    latest = await memory_versions.get_latest(memory_id)
    return 1 if latest is None else latest.version + 1


def _memory_version(
    *,
    item: MemoryItem,
    request: LifecycleTransitionRequest,
    version: int,
) -> MemoryVersion:
    return MemoryVersion(
        id=_uuid("memory_version", item.id, str(version)),
        memory_id=item.id,
        version=version,
        title=item.title,
        content=item.content,
        summary=item.summary,
        status=item.status,
        source_event_ids=item.source_event_ids,
        changed_by="user",
        change_reason=request.reason,
        created_at=request.now,
    )


def _audit_event(
    *,
    request: LifecycleTransitionRequest,
    stage: str,
    input_ref: str | None,
    output_ref: str | None,
    decision: str,
    reason_code: str | None,
    reason_text: str | None,
    source_event_ids: tuple[str, ...],
) -> AuditEvent:
    return AuditEvent(
        id=_uuid("audit", _ENTITY_TYPE, request.memory_id, request.idempotency_key),
        trace_id=request.trace_id,
        entity_type=_ENTITY_TYPE,
        entity_id=request.memory_id,
        stage=stage,
        input_ref=input_ref,
        output_ref=output_ref,
        decision=decision,
        reason_code=reason_code,
        reason_text=reason_text,
        source_event_ids=source_event_ids,
        latency_ms=None,
        created_at=request.now,
        actor_id=request.actor_id,
        idempotency_key=request.idempotency_key,
    )


def _output_ref(action: LifecycleAction, item: MemoryItem) -> str:
    if action in _PIN_ACTIONS:
        return "pinned:true" if item.pinned else "pinned:false"
    return item.status.value


def _status_from_audit_input(audit_event: AuditEvent) -> MemoryStatus:
    if audit_event.input_ref is None:
        raise DomainRuleViolation("lifecycle audit does not include previous status")
    return MemoryStatus(audit_event.input_ref)


def _status_from_audit_output(audit_event: AuditEvent) -> MemoryStatus:
    if audit_event.output_ref is None:
        raise DomainRuleViolation("lifecycle audit does not include output status")
    return MemoryStatus(audit_event.output_ref)


def _successful_audit_action(audit_event: AuditEvent) -> LifecycleAction:
    try:
        return LifecycleAction(audit_event.decision)
    except ValueError as exc:
        raise DomainRuleViolation(
            f"lifecycle audit decision is not a lifecycle action: {audit_event.decision}"
        ) from exc


def _ensure_replay_matches_current_memory(
    *,
    audit_event: AuditEvent,
    action: LifecycleAction,
    memory_item: MemoryItem,
) -> None:
    if action in _PIN_ACTIONS:
        expected_status = _status_from_audit_input(audit_event)
        expected_pinned = _pinned_from_audit_output(audit_event)
        if memory_item.status is not expected_status:
            _raise_replay_status_mismatch(expected_status, memory_item.status)
        if memory_item.pinned is not expected_pinned:
            raise DomainRuleViolation(
                "idempotent lifecycle replay no longer matches pinned state: "
                f"expected {expected_pinned}, found {memory_item.pinned}"
            )
        return

    expected_status = _status_from_audit_output(audit_event)
    if memory_item.status is not expected_status:
        _raise_replay_status_mismatch(expected_status, memory_item.status)


def _pinned_from_audit_output(audit_event: AuditEvent) -> bool:
    if audit_event.output_ref == "pinned:true":
        return True
    if audit_event.output_ref == "pinned:false":
        return False
    raise DomainRuleViolation(
        f"lifecycle pin audit output_ref is not pinned state: {audit_event.output_ref}"
    )


def _raise_replay_status_mismatch(
    expected_status: MemoryStatus,
    current_status: MemoryStatus,
) -> None:
    raise DomainRuleViolation(
        "idempotent lifecycle replay no longer matches memory status: "
        f"expected {expected_status.value}, found {current_status.value}"
    )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
