from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_context import AgentRuntimeEvent, AgentRuntimeEventType
from memwing.api.types import JsonObject, JsonValue
from memwing.api.validation import SchemaValidationError, require_text
from memwing.core.scope import MemoryScope


OPENCLAW_HOOK_EVENT_TYPES: Mapping[str, AgentRuntimeEventType] = {
    "after_tool_call": "tool_call_completed",
    "agent_end": "turn_completed",
    "llm_input": "llm_input_observed",
    "llm_output": "llm_output_observed",
    "session_start": "session_started",
    "session_end": "session_ended",
    "before_compaction": "compaction_started",
    "after_compaction": "compaction_completed",
}


def map_openclaw_ingest_event(payload: Mapping[str, object]) -> AgentRuntimeEvent:
    return _map_event(
        payload,
        default_hook_name="ingest",
        default_event_type="message_ingested",
    )


def map_openclaw_after_turn_event(payload: Mapping[str, object]) -> AgentRuntimeEvent:
    return _map_event(
        payload,
        default_hook_name="afterTurn",
        default_event_type="turn_completed",
    )


def map_openclaw_hook_event(payload: Mapping[str, object]) -> AgentRuntimeEvent:
    hook_name = _optional_text(payload.get("hook_name"), "hook_name")
    if hook_name is None:
        raise SchemaValidationError("hook_name is required")
    event_type = OPENCLAW_HOOK_EVENT_TYPES.get(hook_name)
    if event_type is None:
        raise SchemaValidationError(f"unsupported OpenClaw hook: {hook_name}")
    return _map_event(payload, default_hook_name=hook_name, default_event_type=event_type)


def openclaw_runtime_ref_from_payload(payload: Mapping[str, object]) -> AgentRuntimeRef:
    return AgentRuntimeRef(
        runtime="openclaw",
        agent_id=_required_text(payload.get("agent_id"), "agent_id"),
        workspace_id=_optional_text(payload.get("workspace_id"), "workspace_id"),
        session_id=_optional_text(payload.get("session_id"), "session_id"),
    )


def memory_scope_from_payload(payload: Mapping[str, object]) -> MemoryScope:
    raw_scope = payload.get("scope")
    if not isinstance(raw_scope, Mapping):
        raise SchemaValidationError("scope is required")
    scope = cast(Mapping[str, object], raw_scope)
    return MemoryScope(
        project_memory_space_id=_required_text(
            scope.get("project_memory_space_id"),
            "scope.project_memory_space_id",
        ),
        group_id=_optional_text(scope.get("group_id"), "scope.group_id"),
        thread_id=_optional_text(scope.get("thread_id"), "scope.thread_id"),
        shared_group_id=_optional_text(scope.get("shared_group_id"), "scope.shared_group_id"),
    )


def json_object_from_mapping(value: Mapping[str, object], field_name: str) -> JsonObject:
    json_object: JsonObject = {}
    for key, raw_value in value.items():
        if not isinstance(key, str):
            raise SchemaValidationError(f"{field_name} must use string keys")
        json_object[require_text(key, field_name)] = _json_value(raw_value, field_name)
    return json_object


def _map_event(
    payload: Mapping[str, object],
    *,
    default_hook_name: str,
    default_event_type: AgentRuntimeEventType,
) -> AgentRuntimeEvent:
    runtime_ref = openclaw_runtime_ref_from_payload(payload)
    hook_name = _optional_text(payload.get("hook_name"), "hook_name") or default_hook_name
    run_id = _optional_text(payload.get("run_id"), "run_id")
    message_id = _optional_text(payload.get("message_id"), "message_id")
    tool_call_id = _optional_text(payload.get("tool_call_id"), "tool_call_id")
    sequence = _optional_non_negative_int(payload.get("sequence"), "sequence")
    idempotency_key = _optional_text(payload.get("idempotency_key"), "idempotency_key")
    if idempotency_key is None:
        idempotency_key = stable_openclaw_idempotency_key(
            runtime_ref=runtime_ref,
            hook_name=hook_name,
            run_id=run_id,
            message_id=message_id,
            tool_call_id=tool_call_id,
            sequence=sequence,
        )
    event_type = _event_type(payload.get("event_type"), default_event_type)
    return AgentRuntimeEvent(
        runtime_ref=runtime_ref,
        run_id=run_id,
        message_id=message_id,
        tool_call_id=tool_call_id,
        hook_name=hook_name,
        sequence=sequence,
        idempotency_key=idempotency_key,
        event_type=event_type,
        scope=memory_scope_from_payload(payload),
        content=_optional_text(payload.get("content"), "content"),
        payload=json_object_from_mapping(payload, "payload"),
        event_time=_event_time(payload.get("event_time")),
    )


def stable_openclaw_idempotency_key(
    *,
    runtime_ref: AgentRuntimeRef,
    hook_name: str,
    run_id: str | None,
    message_id: str | None,
    tool_call_id: str | None,
    sequence: int | None,
) -> str:
    terminal_id = message_id or tool_call_id or (
        f"sequence:{sequence}" if sequence is not None else "event"
    )
    return ":".join(
        (
            runtime_ref.runtime,
            runtime_ref.agent_id,
            runtime_ref.session_id or "session",
            run_id or "run",
            hook_name,
            terminal_id,
        )
    )


def _event_type(value: object, default: AgentRuntimeEventType) -> AgentRuntimeEventType:
    if value is None:
        return default
    event_type = _required_text(value, "event_type")
    supported = (
        "message_ingested",
        "turn_completed",
        "tool_call_completed",
        "llm_input_observed",
        "llm_output_observed",
        "session_started",
        "session_ended",
        "compaction_started",
        "compaction_completed",
    )
    if event_type not in supported:
        raise SchemaValidationError("event_type is not supported")
    if event_type != default:
        raise SchemaValidationError("event_type does not match OpenClaw lifecycle mapping")
    return cast(AgentRuntimeEventType, event_type)


def _event_time(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SchemaValidationError("event_time must be an ISO datetime") from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    raise SchemaValidationError("event_time is required")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} is required")
    return require_text(value, field_name)


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be text")
    return require_text(value, field_name)


def _optional_non_negative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SchemaValidationError(f"{field_name} must be a non-negative integer")
    return value


def _json_value(value: object, field_name: str) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return cast(JsonValue, value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return json_object_from_mapping(cast(Mapping[str, object], value), field_name)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(_json_value(item, field_name) for item in value)
    raise SchemaValidationError(f"{field_name} must be JSON serializable")
