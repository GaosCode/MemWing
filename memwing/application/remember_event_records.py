from __future__ import annotations

from datetime import datetime
import uuid

from memwing.core.models import AuditEvent, OutboxJob, SourceEvent


def capture_audit_event(
    *,
    source_event: SourceEvent,
    trace_id: str,
    now: datetime,
) -> AuditEvent:
    return AuditEvent(
        id=_uuid("audit", trace_id, source_event.id, "remember_event.captured"),
        trace_id=trace_id,
        entity_type="source_event",
        entity_id=source_event.id,
        stage="remember_event.captured",
        input_ref=source_event.id,
        output_ref=None,
        decision="accepted",
        reason_code=None,
        reason_text=None,
        source_event_ids=(source_event.id,),
        latency_ms=None,
        created_at=now,
    )


def rejected_audit_event(*, trace_id: str, reason_text: str, now: datetime) -> AuditEvent:
    return AuditEvent(
        id=_uuid("audit", trace_id, "remember_event.rejected"),
        trace_id=trace_id,
        entity_type="remember_event",
        entity_id=trace_id,
        stage="remember_event.rejected",
        input_ref=None,
        output_ref=None,
        decision="rejected",
        reason_code="scope_resolution_failed",
        reason_text=reason_text,
        source_event_ids=(),
        latency_ms=None,
        created_at=now,
    )


def outbox_job(*, source_event: SourceEvent, job_type: str, now: datetime) -> OutboxJob:
    idempotency_key = f"{job_type}:{source_event.id}"
    return OutboxJob(
        id=_uuid("outbox", idempotency_key),
        project_memory_space_id=source_event.project_memory_space_id,
        source_event_id=source_event.id,
        job_type=job_type,
        payload_json={"source_event_id": source_event.id},
        status="pending",
        idempotency_key=idempotency_key,
        aggregate_key=source_event.id,
        attempts=0,
        max_attempts=3,
        priority=100,
        next_run_at=now,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error=None,
        dead_letter_reason=None,
        created_at=now,
        updated_at=now,
    )


def source_event_id(
    *,
    project_memory_space_id: str,
    raw_payload_hash: str,
    runtime_event_idempotency_key: str | None,
) -> str:
    return _uuid(
        "source_event",
        project_memory_space_id,
        raw_payload_hash,
        runtime_event_idempotency_key or "",
    )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
