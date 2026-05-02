from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum

from memwing.api.error_mapping import render_error_body
from memwing.api.types import JsonObject, JsonValue
from memwing.api.validation import SchemaValidationError, require_positive_int, require_text
from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.application.failure_semantics import classify_failure
from memwing.core.errors import ConfigurationFailure, ValidationFailure
from memwing.ports.benchmark_admin import BenchmarkRuntimeBinding, BenchmarkScope


@dataclass(frozen=True, slots=True)
class BenchmarkAdminHttpResponse:
    status_code: int
    body: JsonObject


async def handle_benchmark_admin_request(
    *,
    path: str,
    payload: Mapping[str, object],
    service: BenchmarkAdminService | None,
) -> BenchmarkAdminHttpResponse:
    if service is None:
        failure = classify_failure(
            ConfigurationFailure("benchmark_admin_disabled", "benchmark admin routes are disabled"),
            audit_stage="api.benchmark_admin",
        )
        return BenchmarkAdminHttpResponse(status_code=404, body=render_error_body(failure))

    try:
        if path == "/v1/memwing/admin/benchmark/cleanup-scope":
            result = await service.cleanup_scope(
                scope=_scope(payload),
                runtime_binding=_runtime_binding(payload),
            )
            return BenchmarkAdminHttpResponse(status_code=200, body=_json_object(result))
        if path == "/v1/memwing/admin/benchmark/drain":
            result = await service.drain_scope(
                scope=_scope(payload),
                max_iterations=_positive_int(payload, "max_iterations", default=20),
                batch_size=_positive_int(payload, "batch_size", default=10),
            )
            status_code = 200 if result.drained and result.outbox_dead_lettered == 0 and result.graph_dead_lettered == 0 else 409
            return BenchmarkAdminHttpResponse(status_code=status_code, body=_json_object(result))
        if path == "/v1/memwing/admin/benchmark/readiness":
            result = await service.readiness(
                scope=_scope(payload),
                expected_source_event_ids=tuple(_text_list(payload, "expected_source_event_ids")),
                queries=tuple(_text_list(payload, "queries")),
            )
            return BenchmarkAdminHttpResponse(status_code=200, body=_json_object(result))
    except SchemaValidationError as exc:
        failure = classify_failure(
            ValidationFailure("schema_invalid", str(exc)),
            audit_stage="api.benchmark_admin",
        )
        return BenchmarkAdminHttpResponse(status_code=failure.http_status, body=render_error_body(failure))
    except ValueError as exc:
        failure = classify_failure(
            ValidationFailure("benchmark_admin_invalid_scope", str(exc)),
            audit_stage="api.benchmark_admin",
        )
        return BenchmarkAdminHttpResponse(status_code=failure.http_status, body=render_error_body(failure))

    failure = classify_failure(
        ValidationFailure("route_not_found", "route not found"),
        audit_stage="api.benchmark_admin",
    )
    return BenchmarkAdminHttpResponse(status_code=404, body=render_error_body(failure))


def _scope(payload: Mapping[str, object]) -> BenchmarkScope:
    raw_scope = payload.get("scope")
    if not isinstance(raw_scope, Mapping):
        raise SchemaValidationError("scope is required")
    allowed = {"project_memory_space_id", "group_id", "thread_id", "shared_group_id"}
    unexpected = set(raw_scope) - allowed
    if unexpected:
        raise SchemaValidationError(f"scope.{sorted(unexpected)[0]} is not supported")
    return BenchmarkScope(
        project_memory_space_id=require_text(
            raw_scope.get("project_memory_space_id"),
            "scope.project_memory_space_id",
        ),
        group_id=_optional_text(raw_scope.get("group_id"), "scope.group_id"),
        thread_id=_optional_text(raw_scope.get("thread_id"), "scope.thread_id"),
        shared_group_id=_optional_text(raw_scope.get("shared_group_id"), "scope.shared_group_id"),
    )


def _runtime_binding(payload: Mapping[str, object]) -> BenchmarkRuntimeBinding:
    return BenchmarkRuntimeBinding(
        runtime="openclaw",
        agent_id=require_text(payload.get("agent_id"), "agent_id"),
        workspace_id=_optional_text(payload.get("workspace_id"), "workspace_id"),
        session_id=_optional_text(payload.get("session_id"), "session_id"),
    )


def _positive_int(payload: Mapping[str, object], field_name: str, *, default: int) -> int:
    value = payload.get(field_name, default)
    return require_positive_int(value, field_name)


def _text_list(payload: Mapping[str, object], field_name: str) -> list[str]:
    value = payload.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be an array")
    texts: list[str] = []
    for index, item in enumerate(value):
        texts.append(require_text(item, f"{field_name}[{index}]"))
    return texts


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return require_text(value, field_name)


def _json_object(value: object) -> JsonObject:
    converted = _json_value(value)
    if not isinstance(converted, dict):
        raise TypeError("HTTP response body must be a JSON object")
    return converted


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return str(value)
