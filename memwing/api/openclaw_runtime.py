from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from memwing.api.agent_context import AgentContextRequest, AgentContextResult, RememberEventResult
from memwing.api.openclaw_mock_runtime import OpenClawMockRuntime
from memwing.api.openclaw_payloads import (
    json_object_from_mapping,
    map_openclaw_after_turn_event,
    map_openclaw_hook_event,
    map_openclaw_ingest_event,
    memory_scope_from_payload,
    openclaw_runtime_ref_from_payload,
)
from memwing.api.types import JsonObject
from memwing.api.validation import SchemaValidationError, require_positive_int, require_text
from memwing.ports.agent_runtime import AgentRuntimePort


async def assemble_openclaw_context(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
) -> AgentContextResult:
    request = _context_request_from_payload(payload)
    return await _runtime(runtime).build_context(request)


async def ingest_openclaw_event(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
) -> RememberEventResult:
    event = map_openclaw_ingest_event(payload)
    return await _runtime(runtime).remember_runtime_event(event)


async def complete_openclaw_turn(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
) -> RememberEventResult:
    event = map_openclaw_after_turn_event(payload)
    return await _runtime(runtime).remember_runtime_event(event)


async def observe_openclaw_hook(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
) -> RememberEventResult:
    event = map_openclaw_hook_event(payload)
    return await _runtime(runtime).remember_runtime_event(event)


def delegate_compaction_to_runtime(
    payload: Mapping[str, object],
    delegate_result: Mapping[str, object],
) -> JsonObject:
    return {
        "delegated": True,
        "delegate": "openclaw_runtime",
        "input": json_object_from_mapping(payload, "payload"),
        "result": json_object_from_mapping(delegate_result, "delegate_result"),
    }


def _context_request_from_payload(payload: Mapping[str, object]) -> AgentContextRequest:
    return AgentContextRequest(
        runtime_ref=openclaw_runtime_ref_from_payload(payload),
        scope=memory_scope_from_payload(payload),
        prompt=_optional_text(payload.get("prompt"), "prompt"),
        messages=_messages_from_payload(payload.get("messages")),
        token_budget=_optional_positive_int(payload.get("token_budget"), "token_budget"),
        available_tools=_available_tools(payload.get("available_tools")),
    )


def _messages_from_payload(value: object) -> tuple[JsonObject, ...]:
    if value is None:
        return ()
    if not isinstance(value, tuple | list):
        raise SchemaValidationError("messages must be a list")
    messages: list[JsonObject] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise SchemaValidationError("messages must contain JSON objects")
        messages.append(json_object_from_mapping(cast(Mapping[str, object], item), "messages"))
    return tuple(messages)


def _available_tools(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, tuple | list):
        raise SchemaValidationError("available_tools must be a list")
    return tuple(_required_text(tool, "available_tools") for tool in value)


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} is required")
    return require_text(value, field_name)


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return require_positive_int(value, field_name)


def _runtime(runtime: AgentRuntimePort | None) -> AgentRuntimePort:
    return runtime if runtime is not None else OpenClawMockRuntime()
