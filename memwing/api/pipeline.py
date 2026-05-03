from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum

from memwing.api.error_mapping import render_error_body
from memwing.api.types import JsonObject, JsonValue
from memwing.api.validation import SchemaValidationError, require_text
from memwing.application.failure_semantics import classify_failure
from memwing.application.pipeline_readiness_service import PipelineReadinessService
from memwing.core.errors import ValidationFailure
from memwing.core.pipeline_readiness import (
    PipelineReadinessCommand,
    PipelineReadinessProfile,
)
from memwing.core.scope import EffectiveScope


@dataclass(frozen=True, slots=True)
class PipelineHttpResponse:
    status_code: int
    body: JsonObject


@dataclass(frozen=True, slots=True)
class PipelineScopeRequest:
    project_memory_space_id: str
    group_id: str | None = None
    thread_id: str | None = None
    shared_group_id: str | None = None

    def to_effective_scope(self) -> EffectiveScope:
        return EffectiveScope(
            project_memory_space_id=self.project_memory_space_id,
            group_ids=(self.group_id,) if self.group_id is not None else None,
            thread_id=self.thread_id,
            shared_group_id=self.shared_group_id,
            safe_mode_enabled=self.group_id is not None,
            cross_group_allowed=self.group_id is None,
        )


@dataclass(frozen=True, slots=True)
class PipelineReadinessRequest:
    source_event_ids: tuple[str, ...]
    scope: PipelineScopeRequest
    profile: PipelineReadinessProfile = PipelineReadinessProfile.MINIMAL_INGEST

    def to_command(self) -> PipelineReadinessCommand:
        return PipelineReadinessCommand(
            source_event_ids=self.source_event_ids,
            scope=self.scope.to_effective_scope(),
            profile=self.profile,
        )


@dataclass(frozen=True, slots=True)
class PipelineAwaitRequest(PipelineReadinessRequest):
    timeout_seconds: float = 30.0


async def handle_pipeline_readiness_request(
    *,
    payload: Mapping[str, object],
    service: PipelineReadinessService,
) -> PipelineHttpResponse:
    try:
        command = _command_from_payload(payload)
        result = await service.check(command)
        return PipelineHttpResponse(status_code=200, body=_json_object(result))
    except SchemaValidationError as exc:
        return _validation_response(exc)


async def handle_pipeline_await_request(
    *,
    payload: Mapping[str, object],
    service: PipelineReadinessService,
) -> PipelineHttpResponse:
    try:
        command = _command_from_payload(payload)
        timeout_seconds = _timeout_seconds(payload)
        result = await service.await_ready(command, timeout_seconds=timeout_seconds)
        return PipelineHttpResponse(status_code=200, body=_json_object(result))
    except SchemaValidationError as exc:
        return _validation_response(exc)


def _command_from_payload(payload: Mapping[str, object]) -> PipelineReadinessCommand:
    return _readiness_request_from_payload(payload).to_command()


def _readiness_request_from_payload(payload: Mapping[str, object]) -> PipelineReadinessRequest:
    raw_ids = payload.get("source_event_ids")
    if not isinstance(raw_ids, list | tuple) or not raw_ids:
        raise SchemaValidationError("source_event_ids is required")
    source_event_ids = tuple(require_text(value, "source_event_ids[]") for value in raw_ids)
    profile = _profile(payload.get("profile"))
    scope = _scope(payload.get("scope"))
    return PipelineReadinessRequest(
        source_event_ids=source_event_ids,
        scope=scope,
        profile=profile,
    )


def _profile(value: object) -> PipelineReadinessProfile:
    if value is None:
        return PipelineReadinessProfile.MINIMAL_INGEST
    if not isinstance(value, str):
        raise SchemaValidationError("profile must be a string")
    try:
        return PipelineReadinessProfile(value)
    except ValueError as exc:
        raise SchemaValidationError("profile is not supported") from exc


def _scope(value: object) -> PipelineScopeRequest:
    if not isinstance(value, Mapping):
        raise SchemaValidationError("scope is required")
    project_memory_space_id = require_text(
        _optional_text(value.get("project_memory_space_id")),
        "scope.project_memory_space_id",
    )
    group_id = _optional_text(value.get("group_id"))
    thread_id = _optional_text(value.get("thread_id"))
    shared_group_id = _optional_text(value.get("shared_group_id"))
    return PipelineScopeRequest(
        project_memory_space_id=project_memory_space_id,
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError("scope values must be strings")
    stripped = value.strip()
    return stripped or None


def _timeout_seconds(payload: Mapping[str, object]) -> float:
    value = payload.get("timeout_seconds", 30.0)
    if not isinstance(value, int | float) or value < 0:
        raise SchemaValidationError("timeout_seconds must be a non-negative number")
    return float(value)


def _validation_response(exc: SchemaValidationError) -> PipelineHttpResponse:
    failure = classify_failure(
        ValidationFailure("schema_invalid", str(exc)),
        audit_stage="api.pipeline",
    )
    return PipelineHttpResponse(status_code=failure.http_status, body=render_error_body(failure))


def _json_object(value: object) -> JsonObject:
    converted = _json_value(value)
    if not isinstance(converted, dict):
        raise TypeError("pipeline HTTP response body must be a JSON object")
    return converted


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
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
