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
from memwing.workers.benchmark_drain import BenchmarkDrainResult


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
            _reject_unexpected_payload_fields(
                payload,
                {"scope", "agent_id", "workspace_id", "session_id"},
            )
            scope = _scope(payload)
            result = await service.cleanup_scope(
                scope=scope,
                runtime_binding=_runtime_binding(payload, scope),
            )
            return BenchmarkAdminHttpResponse(
                status_code=200,
                body={
                    "deleted": _cleanup_deleted(result.deleted_counts),
                    "trace_id": f"benchmark_cleanup:{scope.project_memory_space_id}",
                },
            )
        if path == "/v1/memwing/admin/benchmark/drain":
            _reject_unexpected_payload_fields(payload, {"scope", "max_rounds", "batch_size"})
            scope = _scope(payload)
            result = await service.drain_scope(
                scope=scope,
                max_iterations=_positive_int(payload, "max_rounds", default=20),
                batch_size=_positive_int(payload, "batch_size", default=10),
            )
            status_code = (
                200
                if result.drained
                and result.outbox_dead_lettered == 0
                and result.graph_dead_lettered == 0
                else 409
            )
            return BenchmarkAdminHttpResponse(
                status_code=status_code,
                body=_drain_body(result, scope),
            )
        if path == "/v1/memwing/admin/benchmark/readiness":
            _reject_unexpected_payload_fields(payload, {"scope", "expected_source_event_ids", "queries"})
            scope = _scope(payload)
            result = await service.readiness(
                scope=scope,
                expected_source_event_ids=tuple(_text_list(payload, "expected_source_event_ids")),
                queries=tuple(_text_list(payload, "queries")),
            )
            body = _json_object(result)
            body["trace_id"] = f"benchmark_readiness:{scope.project_memory_space_id}"
            return BenchmarkAdminHttpResponse(status_code=200, body=body)
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


def _runtime_binding(payload: Mapping[str, object], scope: BenchmarkScope) -> BenchmarkRuntimeBinding:
    return BenchmarkRuntimeBinding(
        runtime="openclaw",
        agent_id=_optional_text(payload.get("agent_id"), "agent_id") or "main",
        workspace_id=_optional_text(payload.get("workspace_id"), "workspace_id"),
        session_id=_optional_text(payload.get("session_id"), "session_id") or scope.thread_id,
    )


def _positive_int(payload: Mapping[str, object], field_name: str, *, default: int) -> int:
    value = payload.get(field_name, default)
    return require_positive_int(value, field_name)


def _reject_unexpected_payload_fields(payload: Mapping[str, object], allowed: set[str]) -> None:
    unexpected = set(payload) - allowed
    if unexpected:
        raise SchemaValidationError(f"{sorted(unexpected)[0]} is not supported")


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


def _cleanup_deleted(deleted_counts: Mapping[str, int]) -> JsonObject:
    return {
        "source_events": deleted_counts.get("source_events", 0),
        "memory_items": deleted_counts.get("memory_items", 0),
        "outbox_jobs": deleted_counts.get("outbox_jobs", 0),
        "graph_write_jobs": deleted_counts.get("graph_write_jobs", 0),
        "page_memory": deleted_counts.get("memory_pages", 0),
        "working_memory": deleted_counts.get("working_memory_entries", 0),
        "memory_recall_events": deleted_counts.get("memory_recall_events", 0),
    }


def _drain_body(result: BenchmarkDrainResult, scope: BenchmarkScope) -> JsonObject:
    return {
        "outbox": {
            "claimed": result.outbox_claimed,
            "succeeded": result.outbox_succeeded,
            "retried": result.outbox_retried,
            "dead_lettered": result.outbox_dead_lettered,
        },
        "graph_write": {
            "claimed": result.graph_claimed,
            "succeeded": result.graph_succeeded,
            "retried": result.graph_retried,
            "dead_lettered": result.graph_dead_lettered,
        },
        "evidence_indexed": {"source_events": result.evidence_indexed_source_events},
        "pending": {
            "outbox_jobs": result.pending_outbox_jobs,
            "graph_write_jobs": result.pending_graph_write_jobs,
        },
        "trace_id": f"benchmark_drain:{scope.project_memory_space_id}",
    }
