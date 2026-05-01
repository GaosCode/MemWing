from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Callable
import uuid

from memwing.application.failure_semantics import classify_failure
from memwing.core.errors import ScopeResolutionFailure, ValidationFailure
from memwing.core.models import AuditEvent, MemoryItem, MemoryStatus, SourceEvent
from memwing.core.scope import EffectiveScope, effective_scope_matches
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort


REDACTED_SOURCE_CONTENT = "[MemWing source redacted]"


@dataclass(frozen=True, slots=True)
class SourceRedactionCommand:
    source_event_id: str
    scope: EffectiveScope
    actor_id: str
    reason: str
    idempotency_key: str
    trace_id: str
    purge_level: str


@dataclass(frozen=True, slots=True)
class SourceRedactionResult:
    source_event: SourceEvent
    affected_memory_item_ids: tuple[str, ...]
    graph_backend_marker_attempted: bool
    graph_backend_marker_succeeded: bool
    graph_backend_warning: str | None
    trace_id: str


class SourceRedactionService:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        graph_backend: GraphBackendPort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._graph_backend = graph_backend
        self._now = now or (lambda: datetime.now(UTC))

    async def purge_source(self, command: SourceRedactionCommand) -> SourceRedactionResult:
        _validate_command(command)
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="source_event",
                entity_id=command.source_event_id,
                idempotency_key=command.idempotency_key,
            )
            source_event = await tx.source_events.get_source_event(command.source_event_id)
            if source_event is None or not _source_event_in_scope(source_event, command.scope):
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="source_event",
                        entity_id=command.source_event_id,
                        stage="source_redaction.rejected",
                        decision="rejected",
                        reason_code="source_redaction_not_found",
                        reason_text=None,
                        source_event_ids=(command.source_event_id,),
                        actor_id=command.actor_id,
                        idempotency_key=None,
                        trace_id=command.trace_id,
                        now=now,
                    )
                )
                raise ScopeResolutionFailure(
                    "source_redaction_not_found",
                    "The requested source event was not found.",
                )
            if existing_audit is None:
                redacted = await tx.source_events.redact_source_event(
                    source_event_id=command.source_event_id,
                    redacted_content=REDACTED_SOURCE_CONTENT,
                    purged_at=now,
                    purged_by=command.actor_id,
                    purge_reason=command.reason,
                    purge_level=command.purge_level,
                    graph_backend_raw_retained=True,
                )
                if redacted is None:
                    raise ScopeResolutionFailure(
                        "source_redaction_not_found",
                        "The requested source event was not found.",
                    )
                source_event = redacted
                await tx.evidence_chunks.mark_source_redacted(
                    source_event_id=command.source_event_id,
                    invalidated_at=now,
                )
                affected_items = await tx.memory_items.list_by_source_event(command.source_event_id)
                affected_ids = []
                for item in affected_items:
                    if item.project_memory_space_id != command.scope.project_memory_space_id:
                        continue
                    if item.status is MemoryStatus.REMOVED:
                        continue
                    affected_ids.append(item.id)
                    await tx.memory_items.upsert(_redacted_memory_item(item, command.source_event_id, now))
                await tx.memory_pages.mark_needs_rebuild_for_source(
                    source_event_id=command.source_event_id,
                    updated_at=now,
                )
                for candidate in await tx.push_candidates.list_for_project(
                    project_memory_space_id=command.scope.project_memory_space_id,
                    limit=500,
                ):
                    if command.source_event_id in candidate.source_event_ids and candidate.status in (
                        "pending",
                        "approved",
                    ):
                        await tx.push_candidates.update_status(
                            candidate_id=candidate.id,
                            project_memory_space_id=command.scope.project_memory_space_id,
                            status="invalid" if candidate.status == "pending" else "skipped",
                            updated_at=now,
                        )
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="source_event",
                        entity_id=command.source_event_id,
                        stage="source_redaction.succeeded",
                        decision="redacted",
                        reason_code=None,
                        reason_text=command.reason,
                        source_event_ids=(command.source_event_id,),
                        actor_id=command.actor_id,
                        idempotency_key=command.idempotency_key,
                        trace_id=command.trace_id,
                        now=now,
                    )
                )
            else:
                affected_ids = tuple(
                    item.id
                    for item in await tx.memory_items.list_by_source_event(command.source_event_id)
                    if item.project_memory_space_id == command.scope.project_memory_space_id
                )

        marker_attempted = self._graph_backend is not None
        marker_succeeded = False
        marker_warning = None
        if self._graph_backend is not None:
            try:
                await self._graph_backend.mark_source_redacted(
                    command.source_event_id,
                    command.scope,
                )
                marker_succeeded = True
            except Exception as exc:
                failure = classify_failure(exc, audit_stage="source_redaction.graph_backend")
                marker_warning = failure.reason_code
                async with self._unit_of_work.transaction() as tx:
                    await tx.audit_events.record(
                        _audit_event(
                            entity_type="source_event",
                            entity_id=command.source_event_id,
                            stage="source_redaction.graph_backend.warning",
                            decision="warning",
                            reason_code=failure.reason_code,
                            reason_text=failure.safe_message,
                            source_event_ids=(command.source_event_id,),
                            actor_id=command.actor_id,
                            idempotency_key=None,
                            trace_id=command.trace_id,
                            now=self._now(),
                        )
                    )
        return SourceRedactionResult(
            source_event=source_event,
            affected_memory_item_ids=tuple(affected_ids),
            graph_backend_marker_attempted=marker_attempted,
            graph_backend_marker_succeeded=marker_succeeded,
            graph_backend_warning=marker_warning,
            trace_id=command.trace_id,
        )


def _validate_command(command: SourceRedactionCommand) -> None:
    if command.purge_level != "memwing_redaction":
        raise ValidationFailure("invalid_purge_level", "purge_level must be memwing_redaction.")
    if not command.actor_id.strip():
        raise ValidationFailure("actor_required", "actor_id is required.")
    if not command.reason.strip():
        raise ValidationFailure("reason_required", "reason is required.")
    if not command.idempotency_key.strip():
        raise ValidationFailure("idempotency_key_required", "idempotency_key is required.")


def _source_event_in_scope(event: SourceEvent, scope: EffectiveScope) -> bool:
    return event.project_memory_space_id == scope.project_memory_space_id and effective_scope_matches(
        group_id=event.group_id,
        thread_id=event.thread_id,
        shared_group_id=event.shared_group_id,
        scope=scope,
    )


def _redacted_memory_item(item: MemoryItem, source_event_id: str, now: datetime) -> MemoryItem:
    redacted_source_ids = {source_event_id}
    remaining_sources = tuple(
        item_source_id for item_source_id in item.source_event_ids if item_source_id not in redacted_source_ids
    )
    should_invalidate = item.primary_source_event_id == source_event_id or not remaining_sources
    if should_invalidate:
        return replace(
            item,
            status=MemoryStatus.INVALID,
            invalidated_at=now,
            updated_at=now,
            lifecycle_revision=item.lifecycle_revision + 1,
        )
    return replace(
        item,
        status=MemoryStatus.NEEDS_REVIEW,
        updated_at=now,
        lifecycle_revision=item.lifecycle_revision + 1,
    )


def _audit_event(
    *,
    entity_type: str,
    entity_id: str,
    stage: str,
    decision: str,
    reason_code: str | None,
    reason_text: str | None,
    source_event_ids: tuple[str, ...],
    actor_id: str | None,
    idempotency_key: str | None,
    trace_id: str,
    now: datetime,
) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join((stage, entity_id, idempotency_key or str(now))))),
        trace_id=trace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        stage=stage,
        input_ref=None,
        output_ref=None,
        decision=decision,
        reason_code=reason_code,
        reason_text=reason_text,
        source_event_ids=source_event_ids,
        latency_ms=None,
        created_at=now,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        action_ref=decision,
        lifecycle_revision=None,
    )
