from __future__ import annotations

from datetime import datetime
from typing import Callable, Mapping

from memwing.application.control_projection import ControlPushCandidateProjection, project_push_candidate
from memwing.application.control_service_support import (
    _audit_event,
    _not_found,
    _rejected_audit_event,
    _scope_values_match,
)
from memwing.core.errors import ConfigurationFailure, ValidationFailure
from memwing.core.platform import PlatformRef, PushCandidate as PlatformPushCandidate
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.platform_connector import PlatformConnectorPort


class ControlPushServiceMixin:
    _unit_of_work: EventStoreUnitOfWorkPort
    _now: Callable[[], datetime]
    _platform_connectors: Mapping[str, PlatformConnectorPort]

    async def approve_push_candidate(
        self,
        *,
        candidate_id: str,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlPushCandidateProjection:
        return await self._transition_push_candidate(
            candidate_id=candidate_id,
            scope=scope,
            next_status="approved",
            actor_id=actor_id,
            reason=reason,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    async def skip_push_candidate(
        self,
        *,
        candidate_id: str,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlPushCandidateProjection:
        return await self._transition_push_candidate(
            candidate_id=candidate_id,
            scope=scope,
            next_status="skipped",
            actor_id=actor_id,
            reason=reason,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    async def send_push_candidate(
        self,
        *,
        candidate_id: str,
        platform: str,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlPushCandidateProjection:
        connector = self._platform_connectors.get(platform)
        if connector is None:
            raise ConfigurationFailure("platform_connector_missing", "Platform connector is not configured.")

        now = self._now()
        failure: Exception | None = None
        source_events = []
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="push_candidate",
                entity_id=candidate_id,
                idempotency_key=idempotency_key,
            )
            candidate = await tx.push_candidates.get(candidate_id)
            if candidate is None or not _scope_values_match(
                group_id=candidate.group_id,
                thread_id=candidate.thread_id,
                shared_group_id=candidate.shared_group_id,
                scope=scope,
            ):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_push_candidate_send",
                        entity_id=candidate_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                failure = _not_found()
            if failure is None and existing_audit is not None:
                return project_push_candidate(candidate)
            if failure is None and candidate.status != "approved":
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="push_candidate",
                        entity_id=candidate_id,
                        stage="control.push_candidate.send_rejected",
                        decision="rejected",
                        reason_text="Push candidate must be approved before sending.",
                        source_event_ids=candidate.source_event_ids,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                failure = ValidationFailure(
                    "push_candidate_not_approved",
                    "Push candidate must be approved before sending.",
                )
            if failure is None:
                for source_event_id in candidate.source_event_ids:
                    source_event = await tx.source_events.get_source_event(source_event_id)
                    if source_event is not None:
                        source_events.append(source_event)

        if failure is not None:
            raise failure

        platform_ref = _platform_ref_from_source_events(source_events, platform=platform)
        send_result = await connector.send_candidate(
            PlatformPushCandidate(
                id=candidate.id,
                platform_ref=platform_ref,
                content=candidate.content,
                trace_id=trace_id,
            )
        )

        async with self._unit_of_work.transaction() as tx:
            if send_result.delivered:
                updated = await tx.push_candidates.update_status(
                    candidate_id=candidate_id,
                    project_memory_space_id=scope.project_memory_space_id,
                    status="sent",
                    updated_at=now,
                )
                if updated is None:
                    raise _not_found()
                candidate = updated
            await tx.audit_events.record(
                _audit_event(
                    entity_type="push_candidate",
                    entity_id=candidate_id,
                    stage="control.push_candidate.sent" if send_result.delivered else "control.push_candidate.send_failed",
                    decision="sent" if send_result.delivered else "not_delivered",
                    reason_text=reason,
                    source_event_ids=candidate.source_event_ids,
                    actor_id=actor_id,
                    idempotency_key=idempotency_key,
                    trace_id=trace_id,
                    now=now,
                    output_ref=send_result.provider_message_id,
                )
            )
        return project_push_candidate(candidate)

    async def _transition_push_candidate(
        self,
        *,
        candidate_id: str,
        scope: EffectiveScope,
        next_status: str,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlPushCandidateProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="push_candidate",
                entity_id=candidate_id,
                idempotency_key=idempotency_key,
            )
            candidate = await tx.push_candidates.get(candidate_id)
            if candidate is None or not _scope_values_match(
                group_id=candidate.group_id,
                thread_id=candidate.thread_id,
                shared_group_id=candidate.shared_group_id,
                scope=scope,
            ):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_push_candidate",
                        entity_id=candidate_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()
            if existing_audit is None:
                candidate = await tx.push_candidates.update_status(
                    candidate_id=candidate_id,
                    project_memory_space_id=scope.project_memory_space_id,
                    status=next_status,
                    updated_at=now,
                )
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="push_candidate",
                        entity_id=candidate_id,
                        stage=f"control.push_candidate.{next_status}",
                        decision=next_status,
                        reason_text=reason,
                        source_event_ids=candidate.source_event_ids if candidate is not None else (),
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                    )
                )
            if candidate is None:
                raise _not_found()
            return project_push_candidate(candidate)


def _platform_ref_from_source_events(source_events: list[object], *, platform: str) -> PlatformRef:
    for source_event in source_events:
        metadata = getattr(source_event, "metadata", {})
        source_ref = metadata.get("source_ref") if isinstance(metadata, dict) else None
        if not isinstance(source_ref, dict):
            continue
        if source_ref.get("kind") != "platform" or source_ref.get("platform") != platform:
            continue
        channel_id = source_ref.get("channel_id")
        if not isinstance(channel_id, str):
            continue
        tenant_id = source_ref.get("tenant_id")
        thread_id = source_ref.get("thread_id")
        message_id = source_ref.get("message_id")
        return PlatformRef(
            platform=platform,
            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
            channel_id=channel_id,
            thread_id=thread_id if isinstance(thread_id, str) else None,
            message_id=message_id if isinstance(message_id, str) else None,
        )
    raise ValidationFailure(
        "push_candidate_platform_ref_missing",
        "Push candidate does not have a source event for this platform.",
    )
