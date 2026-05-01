from __future__ import annotations

from datetime import datetime
import uuid

from memwing.core.errors import ScopeResolutionFailure
from memwing.core.models import AuditEvent
from memwing.core.scope import EffectiveScope, effective_scope_matches


def _scope_values_match(
    *,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
    scope: EffectiveScope,
) -> bool:
    return effective_scope_matches(
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
        scope=scope,
    )


def _not_found() -> ScopeResolutionFailure:
    return ScopeResolutionFailure(
        "control_projection_not_found",
        "The requested control plane resource was not found.",
    )


def _audit_event(
    *,
    entity_type: str,
    entity_id: str,
    stage: str,
    decision: str,
    reason_text: str | None,
    source_event_ids: tuple[str, ...],
    actor_id: str | None,
    idempotency_key: str | None,
    trace_id: str,
    now: datetime,
    output_ref: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        id=_uuid("audit", entity_type, entity_id, idempotency_key or stage),
        trace_id=trace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        stage=stage,
        input_ref=None,
        output_ref=output_ref,
        decision=decision,
        reason_code=None,
        reason_text=reason_text,
        source_event_ids=source_event_ids,
        latency_ms=None,
        created_at=now,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        action_ref=decision,
        lifecycle_revision=None,
    )


def _rejected_audit_event(
    *,
    entity_type: str,
    entity_id: str,
    trace_id: str,
    now: datetime,
) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid4()),
        trace_id=trace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        stage="control.memory_detail.rejected",
        input_ref=entity_id,
        output_ref=None,
        decision="rejected",
        reason_code="control_projection_not_found",
        reason_text=None,
        source_event_ids=(),
        latency_ms=None,
        created_at=now,
        actor_id=None,
        idempotency_key=None,
        action_ref=None,
        lifecycle_revision=None,
    )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
