from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from memwing.core.models import AuditEvent, OutboxJob, SourceEvent
from memwing.core.scope import (
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)


Row = Mapping[str, object]


def source_event_from_row(row: Row) -> SourceEvent:
    return SourceEvent(
        id=_text(row, "id"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        group_id=_optional_text(row, "group_id"),
        thread_id=_optional_text(row, "thread_id"),
        shared_group_id=_optional_text(row, "shared_group_id"),
        author_id=_optional_text(row, "author_id"),
        author_name=_optional_text(row, "author_name"),
        source_type=_text(row, "source_type"),
        content=_text(row, "content"),
        content_preview=_text(row, "content_preview"),
        source_url=_optional_text(row, "source_url"),
        event_time=_datetime(row, "event_time"),
        raw_payload_hash=_text(row, "raw_payload_hash"),
        metadata=_dict(row, "metadata_json"),
        purged_at=_optional_datetime(row, "purged_at"),
        purged_by=_optional_text(row, "purged_by"),
        purge_reason=_optional_text(row, "purge_reason"),
        purge_level=_text(row, "purge_level"),
        graph_backend_raw_retained=_bool(row, "graph_backend_raw_retained"),
        created_at=_datetime(row, "created_at"),
        runtime_event_idempotency_key=_optional_text(row, "runtime_event_idempotency_key"),
    )


def audit_event_from_row(row: Row) -> AuditEvent:
    return AuditEvent(
        id=_text(row, "id"),
        trace_id=_text(row, "trace_id"),
        entity_type=_text(row, "entity_type"),
        entity_id=_text(row, "entity_id"),
        stage=_text(row, "stage"),
        input_ref=_optional_text(row, "input_ref"),
        output_ref=_optional_text(row, "output_ref"),
        decision=_text(row, "decision"),
        reason_code=_optional_text(row, "reason_code"),
        reason_text=_optional_text(row, "reason_text"),
        source_event_ids=tuple(_sequence(row, "source_event_ids")),
        latency_ms=_optional_int(row, "latency_ms"),
        created_at=_datetime(row, "created_at"),
    )


def outbox_job_from_row(row: Row) -> OutboxJob:
    return OutboxJob(
        id=_text(row, "id"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        source_event_id=_text(row, "source_event_id"),
        job_type=_text(row, "job_type"),
        payload_json=_dict(row, "payload_json"),
        status=_text(row, "status"),
        idempotency_key=_text(row, "idempotency_key"),
        aggregate_key=_optional_text(row, "aggregate_key"),
        attempts=_int(row, "attempts"),
        max_attempts=_int(row, "max_attempts"),
        priority=_int(row, "priority"),
        next_run_at=_datetime(row, "next_run_at"),
        locked_at=_optional_datetime(row, "locked_at"),
        locked_by=_optional_text(row, "locked_by"),
        lock_expires_at=_optional_datetime(row, "lock_expires_at"),
        last_error=_optional_text(row, "last_error"),
        dead_letter_reason=_optional_text(row, "dead_letter_reason"),
        created_at=_datetime(row, "created_at"),
        updated_at=_datetime(row, "updated_at"),
    )


def project_memory_space_from_row(row: Row) -> ProjectMemorySpace:
    return ProjectMemorySpace(
        id=_text(row, "id"),
        name=_text(row, "name"),
        default_safe_mode_enabled=_bool(row, "default_safe_mode_enabled"),
    )


def runtime_scope_binding_from_row(row: Row) -> RuntimeScopeBinding:
    return RuntimeScopeBinding(
        runtime=_text(row, "runtime"),
        agent_id=_text(row, "agent_id"),
        workspace_id=_optional_text(row, "workspace_id"),
        session_key_pattern=_text(row, "session_key_pattern"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
    )


def platform_scope_binding_from_row(row: Row) -> PlatformScopeBinding:
    return PlatformScopeBinding(
        platform=_text(row, "platform"),
        tenant_id=_optional_text(row, "tenant_id"),
        channel_id=_text(row, "channel_id"),
        thread_id=_optional_text(row, "thread_id"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        group_id=_text(row, "group_id"),
    )


def group_memory_settings_from_row(row: Row) -> GroupMemorySettings:
    return GroupMemorySettings(
        project_memory_space_id=_text(row, "project_memory_space_id"),
        group_id=_text(row, "group_id"),
        safe_mode_enabled=_bool(row, "safe_mode_enabled"),
        shared_group_id=_optional_text(row, "shared_group_id"),
    )


def _text(row: Row, key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be str")
    return value


def _optional_text(row: Row, key: str) -> str | None:
    value = row[key]
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"{key} must be str or None")


def _datetime(row: Row, key: str) -> datetime:
    value = row[key]
    if not isinstance(value, datetime):
        raise TypeError(f"{key} must be datetime")
    return value


def _optional_datetime(row: Row, key: str) -> datetime | None:
    value = row[key]
    if value is None or isinstance(value, datetime):
        return value
    raise TypeError(f"{key} must be datetime or None")


def _bool(row: Row, key: str) -> bool:
    value = row[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be bool")
    return value


def _int(row: Row, key: str) -> int:
    value = row[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} must be int")
    return value


def _optional_int(row: Row, key: str) -> int | None:
    value = row[key]
    if value is None or isinstance(value, int):
        return value
    raise TypeError(f"{key} must be int or None")


def _float(row: Row, key: str) -> float:
    value = row[key]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise TypeError(f"{key} must be float")


def _optional_float(row: Row, key: str) -> float | None:
    value = row[key]
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise TypeError(f"{key} must be float or None")


def _float_sequence_or_none(row: Row, key: str) -> tuple[float, ...] | None:
    value = row[key]
    if value is None:
        return None
    if isinstance(value, tuple | list) and all(
        isinstance(item, int | float) and not isinstance(item, bool) for item in value
    ):
        return tuple(float(item) for item in value)
    raise TypeError(f"{key} must be a sequence of float or None")


def _dict(row: Row, key: str) -> dict[str, object]:
    value = row[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be dict")
    return value


def _sequence(row: Row, key: str) -> tuple[str, ...]:
    value = row[key]
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise TypeError(f"{key} must be a sequence of str")
