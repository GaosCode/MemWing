from __future__ import annotations

from dataclasses import dataclass
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from memwing.application.control_projection import ControlPushCandidateProjection, project_push_candidate
from memwing.application.push_trigger_service import (
    select_push_candidate,
    sendable_push_candidates,
    should_trigger_push,
)
from memwing.application.control_service_support import (
    _audit_event,
    _not_found,
    _rejected_audit_event,
    _scope_values_match,
)
from memwing.core.errors import ConfigurationFailure, ValidationFailure
from memwing.core.models import MemoryItem, PushCandidate
from memwing.core.platform import PlatformRef, PushCandidate as PlatformPushCandidate
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.platform_connector import PlatformConnectorPort


@dataclass(frozen=True, slots=True)
class OpenClawPushCardProjection:
    candidate_id: str | None
    title: str | None
    text: str | None
    presentation: dict[str, object] | None
    trace_id: str


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
        delivery_source_event_id: str | None = None,
    ) -> ControlPushCandidateProjection:
        connector = self._platform_connectors.get(platform)
        if connector is None:
            raise ConfigurationFailure("platform_connector_missing", "Platform connector is not configured.")

        now = self._now()
        failure: Exception | None = None
        source_events = []
        delivery_source_events = []
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
                if delivery_source_event_id is not None:
                    delivery_source_event = await tx.source_events.get_source_event(delivery_source_event_id)
                    if delivery_source_event is None or not _scope_values_match(
                        group_id=delivery_source_event.group_id,
                        thread_id=delivery_source_event.thread_id,
                        shared_group_id=delivery_source_event.shared_group_id,
                        scope=scope,
                    ):
                        failure = ValidationFailure(
                            "push_candidate_delivery_source_missing",
                            "Push candidate delivery source event is missing or outside scope.",
                        )
                    else:
                        delivery_source_events.append(delivery_source_event)
                for source_event_id in candidate.source_event_ids:
                    source_event = await tx.source_events.get_source_event(source_event_id)
                    if source_event is not None:
                        source_events.append(source_event)

        if failure is not None:
            raise failure

        try:
            platform_ref = _platform_ref_from_source_events(
                delivery_source_events,
                platform=platform,
            )
        except ValidationFailure:
            platform_ref = _platform_ref_from_source_events(source_events, platform=platform)
        send_result = await connector.send_candidate(
            PlatformPushCandidate(
                id=candidate.id,
                platform_ref=platform_ref,
                title=candidate.title,
                kind=candidate.type,
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

    async def prepare_openclaw_push_card(
        self,
        *,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
        trigger_content: str | None = None,
    ) -> OpenClawPushCardProjection:
        if trigger_content is not None and not should_trigger_push(trigger_content):
            return _empty_openclaw_push_card(trace_id)

        now = self._now()
        memory_items: list[MemoryItem] = []
        async with self._unit_of_work.transaction() as tx:
            candidates = await tx.push_candidates.list_for_project(
                project_memory_space_id=scope.project_memory_space_id,
                limit=20,
                sort="priority",
            )
            selected = select_push_candidate(sendable_push_candidates(candidates), scope=scope)
            if selected is None:
                return _empty_openclaw_push_card(trace_id)
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="push_candidate",
                entity_id=selected.id,
                idempotency_key=idempotency_key,
            )
            if existing_audit is None:
                if selected.status == "pending":
                    approved = await tx.push_candidates.update_status(
                        candidate_id=selected.id,
                        project_memory_space_id=scope.project_memory_space_id,
                        status="approved",
                        updated_at=now,
                    )
                    if approved is None:
                        raise _not_found()
                    selected = approved
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="push_candidate",
                        entity_id=selected.id,
                        stage="control.push_candidate.openclaw_prepared",
                        decision="prepared",
                        reason_text=reason,
                        source_event_ids=selected.source_event_ids,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                    )
                )
            for memory_item_id in selected.memory_item_ids:
                memory_item = await tx.memory_items.get(memory_item_id)
                if memory_item is not None and _scope_values_match(
                    group_id=memory_item.group_id,
                    thread_id=memory_item.thread_id,
                    shared_group_id=memory_item.shared_group_id,
                    scope=scope,
                ):
                    memory_items.append(memory_item)
        return _openclaw_push_card(selected, memory_items=tuple(memory_items), trace_id=trace_id)

    async def ack_openclaw_push_card(
        self,
        *,
        candidate_id: str,
        scope: EffectiveScope,
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
                        entity_type="control_push_candidate_openclaw_ack",
                        entity_id=candidate_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()
            if existing_audit is None and candidate.status != "sent":
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
                        stage="control.push_candidate.openclaw_sent",
                        decision="sent",
                        reason_text=reason,
                        source_event_ids=candidate.source_event_ids,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                        output_ref="openclaw:reply_dispatch",
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


def _empty_openclaw_push_card(trace_id: str) -> OpenClawPushCardProjection:
    return OpenClawPushCardProjection(
        candidate_id=None,
        title=None,
        text=None,
        presentation=None,
        trace_id=trace_id,
    )


def _openclaw_push_card(
    candidate: PushCandidate,
    *,
    memory_items: tuple[MemoryItem, ...] = (),
    trace_id: str,
) -> OpenClawPushCardProjection:
    primary_text = _push_card_primary_text(candidate, memory_items)
    rationale = _push_card_rationale(candidate, primary_text)
    blocks: list[dict[str, object]] = []
    if rationale is not None:
        blocks.append({"type": "text", "text": f"推送理由：{rationale}"})
    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "context",
                "text": f"MemWing | {candidate.type} | trace {trace_id}",
            },
        ]
    )
    return OpenClawPushCardProjection(
        candidate_id=candidate.id,
        title=candidate.title,
        text=primary_text,
        presentation={
            "title": candidate.title,
            "tone": "info",
            "blocks": tuple(blocks),
        },
        trace_id=trace_id,
    )


def _push_card_primary_text(candidate: PushCandidate, memory_items: tuple[MemoryItem, ...]) -> str:
    for item in memory_items:
        content = _card_text(item.content)
        if content is not None:
            return content
    content = _card_text(candidate.content)
    if content is not None:
        return content
    return candidate.title


def _push_card_rationale(candidate: PushCandidate, primary_text: str) -> str | None:
    content = _card_text(candidate.content)
    if content is None or content == primary_text:
        return None
    return content


def _card_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


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
        receive_id_type = source_ref.get("receive_id_type")
        return PlatformRef(
            platform=platform,
            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
            channel_id=channel_id,
            thread_id=thread_id if isinstance(thread_id, str) else None,
            message_id=message_id if isinstance(message_id, str) else None,
            receive_id_type=receive_id_type if isinstance(receive_id_type, str) else None,
        )
    for source_event in source_events:
        metadata = getattr(source_event, "metadata", {})
        platform_ref = _platform_ref_from_agent_runtime_metadata(metadata, platform=platform)
        if platform_ref is not None:
            return platform_ref
    raise ValidationFailure(
        "push_candidate_platform_ref_missing",
        "Push candidate does not have a source event for this platform.",
    )


def _platform_ref_from_agent_runtime_metadata(
    metadata: object,
    *,
    platform: str,
) -> PlatformRef | None:
    if not isinstance(metadata, dict):
        return None
    source_ref = metadata.get("source_ref")
    if not isinstance(source_ref, dict) or source_ref.get("kind") != "agent_runtime":
        return None
    adapter_metadata = metadata.get("adapter_metadata")
    payload = adapter_metadata.get("payload") if isinstance(adapter_metadata, dict) else None
    if isinstance(payload, dict):
        parsed = _platform_ref_from_payload(payload.get("platformRef") or payload.get("platform_ref"), platform=platform)
        if parsed is not None:
            return parsed
        session_key = payload.get("sessionKey") or payload.get("session_key")
        parsed = _platform_ref_from_feishu_session_key(session_key, platform=platform)
        if parsed is not None:
            return parsed
    parsed = _platform_ref_from_feishu_session_key(source_ref.get("session_id"), platform=platform)
    if parsed is not None:
        return parsed
    return _platform_ref_from_openclaw_session_registry(source_ref, platform=platform)


def _platform_ref_from_payload(value: object, *, platform: str) -> PlatformRef | None:
    if not isinstance(value, dict) or value.get("platform") != platform:
        return None
    channel_id = value.get("channel_id") or value.get("channelId")
    if not isinstance(channel_id, str) or not channel_id.strip():
        return None
    tenant_id = value.get("tenant_id") or value.get("tenantId")
    thread_id = value.get("thread_id") or value.get("threadId")
    message_id = value.get("message_id") or value.get("messageId")
    receive_id_type = value.get("receive_id_type") or value.get("receiveIdType")
    return PlatformRef(
        platform=platform,
        tenant_id=tenant_id if isinstance(tenant_id, str) else None,
        channel_id=channel_id,
        thread_id=thread_id if isinstance(thread_id, str) else None,
        message_id=message_id if isinstance(message_id, str) else None,
        receive_id_type=receive_id_type if isinstance(receive_id_type, str) else None,
    )


def _platform_ref_from_feishu_session_key(value: object, *, platform: str) -> PlatformRef | None:
    if platform != "feishu" or not isinstance(value, str):
        return None
    parts = [part for part in value.split(":") if part]
    if len(parts) < 5 or parts[0] != "agent" or parts[2] != "feishu":
        return None

    peer_kind_index = 3
    if len(parts) > peer_kind_index + 1 and parts[peer_kind_index + 1] == "direct":
        peer_kind_index += 1
    if len(parts) <= peer_kind_index + 1:
        return None
    peer_kind = parts[peer_kind_index]
    peer_id = parts[peer_kind_index + 1]
    if peer_kind not in ("direct", "channel", "group") or not peer_id:
        return None
    thread_id = None
    if "thread" in parts[peer_kind_index + 2 :]:
        thread_index = parts.index("thread", peer_kind_index + 2)
        if len(parts) > thread_index + 1:
            thread_id = parts[thread_index + 1]
    return PlatformRef(
        platform="feishu",
        tenant_id=None,
        channel_id=peer_id,
        thread_id=thread_id,
        message_id=None,
        receive_id_type="open_id" if peer_kind == "direct" else "chat_id",
    )


def _platform_ref_from_openclaw_session_registry(
    source_ref: Mapping[str, object],
    *,
    platform: str,
) -> PlatformRef | None:
    if platform != "feishu" or source_ref.get("runtime") != "openclaw":
        return None
    session_id = source_ref.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    agent_id = source_ref.get("agent_id")
    sessions_file = _openclaw_sessions_file(agent_id if isinstance(agent_id, str) and agent_id else "main")
    try:
        raw_sessions = json.loads(sessions_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw_sessions, dict):
        return None
    for session_key, entry in raw_sessions.items():
        if not isinstance(session_key, str) or not isinstance(entry, dict):
            continue
        if entry.get("sessionId") != session_id:
            continue
        parsed = _platform_ref_from_feishu_session_key(session_key, platform=platform)
        if parsed is not None:
            return parsed
        return _platform_ref_from_openclaw_delivery_context(entry.get("deliveryContext"), platform=platform)
    return None


def _openclaw_sessions_file(agent_id: str) -> Path:
    override = os.environ.get("MEMWING_OPENCLAW_SESSIONS_FILE")
    if override:
        return Path(override).expanduser()
    openclaw_home = os.environ.get("OPENCLAW_HOME")
    root = Path(openclaw_home).expanduser() if openclaw_home else Path.home() / ".openclaw"
    return root / "agents" / agent_id / "sessions" / "sessions.json"


def _platform_ref_from_openclaw_delivery_context(
    value: object,
    *,
    platform: str,
) -> PlatformRef | None:
    if platform != "feishu" or not isinstance(value, dict) or value.get("channel") != "feishu":
        return None
    to = value.get("to")
    if not isinstance(to, str) or ":" not in to:
        return None
    kind, _, receive_id = to.partition(":")
    if not receive_id:
        return None
    if kind == "user":
        receive_id_type = "open_id"
    elif kind in {"chat", "group"}:
        receive_id_type = "chat_id"
    else:
        return None
    return PlatformRef(
        platform="feishu",
        tenant_id=None,
        channel_id=receive_id,
        thread_id=None,
        message_id=None,
        receive_id_type=receive_id_type,
    )
