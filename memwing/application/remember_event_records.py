from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import uuid

from memwing.application.remember_event_command import RememberEventCommand
from memwing.core.models import AuditEvent, OutboxJob, SourceEvent
from memwing.application.scope_resolver import ResolvedScope
from memwing.core.scope import EffectiveScope


@dataclass(frozen=True, slots=True)
class RememberEventPlan:
    source_event: SourceEvent
    audit_events: tuple[AuditEvent, ...]
    outbox_jobs: tuple[OutboxJob, ...]


class SourceEventIdentity:
    @staticmethod
    def dedupe_hash(payload: object) -> str:
        if isinstance(payload, bytes):
            encoded = payload
        else:
            encoded = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def deterministic_id(
        *,
        project_memory_space_id: str,
        dedupe_hash: str,
        runtime_event_idempotency_key: str | None,
    ) -> str:
        return source_event_id(
            project_memory_space_id=project_memory_space_id,
            raw_payload_hash=dedupe_hash,
            runtime_event_idempotency_key=runtime_event_idempotency_key,
        )


class SourceEventNormalizer:
    def normalize(
        self,
        command: RememberEventCommand,
        resolved_scope: ResolvedScope,
        *,
        now: datetime,
    ) -> SourceEvent:
        dedupe_hash = SourceEventIdentity.dedupe_hash(command.payload_for_dedupe_hash)
        runtime_key = (
            command.idempotency_key if command.source_ref.kind == "agent_runtime" else None
        )
        return SourceEvent(
            id=SourceEventIdentity.deterministic_id(
                project_memory_space_id=resolved_scope.effective_scope.project_memory_space_id,
                dedupe_hash=dedupe_hash,
                runtime_event_idempotency_key=runtime_key,
            ),
            project_memory_space_id=resolved_scope.effective_scope.project_memory_space_id,
            group_id=resolved_scope.source_group_id,
            thread_id=resolved_scope.thread_id,
            shared_group_id=resolved_scope.shared_group_id,
            author_id=command.author.id,
            author_name=command.author.name,
            source_type=command.source_type,
            content=command.content,
            content_preview=_content_preview(command.content),
            source_url=command.source_url,
            event_time=command.event_time,
            raw_payload_hash=dedupe_hash,
            metadata={
                "source_ref": command.source_ref.to_metadata(),
                "adapter_metadata": command.adapter_metadata,
            },
            purged_at=None,
            purged_by=None,
            purge_reason=None,
            purge_level="none",
            graph_backend_raw_retained=False,
            created_at=now,
            runtime_event_idempotency_key=runtime_key,
        )


class RememberEventRecordFactory:
    def build_plan(
        self,
        *,
        source_event: SourceEvent,
        trace_id: str,
        outbox_job_types: tuple[str, ...],
    ) -> RememberEventPlan:
        return RememberEventPlan(
            source_event=source_event,
            audit_events=(
                capture_audit_event(
                    source_event=source_event,
                    trace_id=trace_id,
                    now=source_event.created_at,
                ),
            ),
            outbox_jobs=tuple(
                outbox_job(
                    source_event=source_event,
                    job_type=job_type,
                    now=source_event.created_at,
                )
                for job_type in outbox_job_types
            ),
        )


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
        aggregate_key=outbox_aggregate_key(source_event=source_event, job_type=job_type),
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


def _content_preview(content: str) -> str:
    return content[:240]


def outbox_aggregate_key(*, source_event: SourceEvent, job_type: str) -> str:
    if job_type == "long_term_filter.classify":
        return long_term_filter_trigger_key(
            project_memory_space_id=source_event.project_memory_space_id,
            group_id=source_event.group_id,
            thread_id=source_event.thread_id,
            shared_group_id=source_event.shared_group_id,
        )
    if job_type == "page_memory.maybe_rebuild":
        return page_memory_trigger_key(
            source_event.project_memory_space_id,
            group_id=source_event.group_id,
            thread_id=source_event.thread_id,
        )
    return source_event.id


def long_term_filter_trigger_key(
    *,
    project_memory_space_id: str,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
) -> str:
    return ":".join(
        (
            "long_term_filter",
            project_memory_space_id,
            group_id or "",
            thread_id or "",
            shared_group_id or "",
        )
    )


def page_memory_trigger_key(
    project_memory_space_id: str,
    *,
    group_id: str | None,
    thread_id: str | None,
) -> str:
    if thread_id is not None:
        scope_type = "thread"
        scope_id = thread_id
    elif group_id is not None:
        scope_type = "group"
        scope_id = group_id
    else:
        scope_type = "project"
        scope_id = project_memory_space_id
    return ":".join(("page_memory", project_memory_space_id, scope_type, scope_id))


def long_term_filter_trigger_key_for_scope(scope: EffectiveScope) -> str:
    group_id = scope.group_ids[0] if scope.group_ids and len(scope.group_ids) == 1 else None
    return long_term_filter_trigger_key(
        project_memory_space_id=scope.project_memory_space_id,
        group_id=group_id,
        thread_id=scope.thread_id,
        shared_group_id=scope.shared_group_id,
    )


def page_memory_trigger_key_for_scope(scope: EffectiveScope) -> str:
    group_id = scope.group_ids[0] if scope.group_ids and len(scope.group_ids) == 1 else None
    return page_memory_trigger_key(
        scope.project_memory_space_id,
        group_id=group_id,
        thread_id=scope.thread_id,
    )
