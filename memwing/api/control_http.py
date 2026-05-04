from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import uuid

from memwing.api.envelopes import MutationEnvelope
from memwing.api.error_mapping import render_error_body
from memwing.api.json_codec import json_object
from memwing.api.types import JsonObject
from memwing.api.validation import SchemaValidationError, require_text
from memwing.application.control_service import ControlService
from memwing.application.failure_semantics import classify_failure
from memwing.application.scope_resolver import ScopeResolutionError, ScopeResolver
from memwing.application.source_redaction_service import (
    SourceRedactionCommand,
    SourceRedactionService,
)
from memwing.core.errors import MemWingFailure, ScopeResolutionFailure, ValidationFailure
from memwing.core.lifecycle import LifecycleAction
from memwing.core.scope import MemoryScope


@dataclass(frozen=True, slots=True)
class ControlHttpServices:
    control: ControlService
    scope_resolver: ScopeResolver
    source_redaction: SourceRedactionService | None = None


@dataclass(frozen=True, slots=True)
class ControlHttpResponse:
    status_code: int
    body: JsonObject


async def handle_control_http_request(
    *,
    method: str,
    path: str,
    query: Mapping[str, str],
    payload: Mapping[str, object],
    services: ControlHttpServices,
) -> ControlHttpResponse:
    try:
        response_body = await _dispatch(
            method=method.upper(),
            path=path,
            query=query,
            payload=payload,
            services=services,
        )
        return ControlHttpResponse(status_code=_success_status(method, path), body=response_body)
    except SchemaValidationError as exc:
        failure = classify_failure(
            ValidationFailure("schema_invalid", str(exc)),
            audit_stage="api.control_http",
        )
        return ControlHttpResponse(status_code=failure.http_status, body=render_error_body(failure))
    except ScopeResolutionError as exc:
        failure = classify_failure(
            ScopeResolutionFailure("scope_resolution_failed", str(exc)),
            audit_stage="api.control_http",
        )
        return ControlHttpResponse(status_code=404, body=render_error_body(failure))
    except MemWingFailure as exc:
        failure = classify_failure(exc, audit_stage="api.control_http")
        return ControlHttpResponse(
            status_code=_http_status_override(exc, failure.http_status),
            body=render_error_body(failure),
        )
    except Exception as exc:
        failure = classify_failure(exc, audit_stage="api.control_http")
        return ControlHttpResponse(status_code=failure.http_status, body=render_error_body(failure))


async def _dispatch(
    *,
    method: str,
    path: str,
    query: Mapping[str, str],
    payload: Mapping[str, object],
    services: ControlHttpServices,
) -> JsonObject:
    if method == "GET":
        return await _dispatch_get(path=path, query=query, services=services)
    if method in ("PATCH", "POST"):
        return await _dispatch_mutation(
            method=method,
            path=path,
            query=query,
            payload=payload,
            services=services,
        )
    raise ValidationFailure("method_not_allowed", "method not allowed")


async def _dispatch_get(
    *,
    path: str,
    query: Mapping[str, str],
    services: ControlHttpServices,
) -> JsonObject:
    if path == "/v1/control/integrations":
        return json_object(
            await services.control.get_integrations(
                trace_id=_trace_id_from_query(query, "control:integrations")
            )
        )

    scope = await _scope_from_query(query, services.scope_resolver)
    trace_id = _trace_id_from_query(query, "control:read")
    limit = _limit_from_query(query)
    cursor = _optional_query_text(query, "cursor")
    sort = query.get("sort") or "updated_at"

    if path == "/v1/control/summary":
        return json_object(
            await services.control.get_summary(scope=scope, limit=limit, trace_id=trace_id)
        )
    if path in ("/v1/control/memories", "/v1/control/pending"):
        return json_object(
            await services.control.list_memories(
                scope=scope,
                limit=limit,
                cursor=cursor,
                sort=sort,
                trace_id=trace_id,
            )
        )
    if path == "/v1/control/forgetting-review":
        return json_object(
            await services.control.list_forgetting_review(
                scope=scope,
                limit=limit,
                cursor=cursor,
                sort=sort,
                trace_id=trace_id,
            )
        )
    if path == "/v1/control/maintenance":
        return json_object(
            await services.control.get_maintenance(
                scope=scope,
                limit=limit,
                cursor=cursor,
                jobs_cursor=_optional_query_text(query, "jobs_cursor"),
                push_candidates_cursor=_optional_query_text(query, "push_candidates_cursor"),
                sort=sort,
                trace_id=trace_id,
            )
        )
    if path == "/v1/control/pages":
        return json_object(
            await services.control.list_pages(
                scope=scope,
                limit=limit,
                cursor=cursor,
                sort=sort,
                trace_id=trace_id,
            )
        )
    if path == "/v1/control/source-events":
        return json_object(
            await services.control.list_source_events(
                scope=scope,
                limit=limit,
                cursor=cursor,
                sort=sort,
                trace_id=trace_id,
            )
        )
    if path == "/v1/control/settings":
        return json_object(await services.control.get_settings(scope=scope, trace_id=trace_id))
    parts = _path_parts(path)
    if len(parts) == 4 and parts[:3] == ("v1", "control", "memories"):
        return json_object(
            await services.control.get_memory_detail(
                memory_id=parts[3],
                scope=scope,
                trace_id=trace_id,
            )
        )
    if len(parts) == 5 and parts[:3] == ("v1", "control", "memories") and parts[4] == "versions":
        versions = await services.control.list_memory_versions(
            memory_id=parts[3],
            scope=scope,
            limit=limit,
            trace_id=trace_id,
        )
        return json_object({"items": versions, "next_cursor": None, "trace_id": trace_id})
    if len(parts) == 4 and parts[:3] == ("v1", "control", "pages"):
        return json_object(
            await services.control.get_page_detail(
                page_id=parts[3],
                scope=scope,
                limit=limit,
                trace_id=trace_id,
            )
        )
    if len(parts) == 4 and parts[:3] == ("v1", "control", "source-events"):
        return json_object(
            await services.control.get_source_event_detail(
                source_event_id=parts[3],
                scope=scope,
                trace_id=trace_id,
            )
        )

    raise ValidationFailure("route_not_found", "route not found")


async def _dispatch_mutation(
    *,
    method: str,
    path: str,
    query: Mapping[str, str],
    payload: Mapping[str, object],
    services: ControlHttpServices,
) -> JsonObject:
    scope = await _scope_from_query(query, services.scope_resolver)
    envelope = _mutation_envelope(payload)
    trace_id = envelope.trace_id or _generated_trace_id(path)
    parts = _path_parts(path)

    if method == "PATCH" and len(parts) == 3 and parts[:2] == ("v1", "memory"):
        result = await services.control.edit_memory(
            memory_id=parts[2],
            scope=scope,
            title=_required_body_text(payload, "title"),
            content=_required_body_text(payload, "content"),
            summary=_optional_body_text(payload, "summary"),
            actor_id=envelope.actor_id,
            reason=envelope.reason,
            idempotency_key=envelope.idempotency_key,
            trace_id=trace_id,
        )
        return _mutation_body(result, trace_id=trace_id)

    if method == "POST" and len(parts) == 4 and parts[:2] == ("v1", "memory"):
        if parts[3] == "restore-version":
            result = await services.control.restore_memory_version(
                memory_id=parts[2],
                version=_required_body_int(payload, "version"),
                scope=scope,
                actor_id=envelope.actor_id,
                reason=envelope.reason,
                idempotency_key=envelope.idempotency_key,
                trace_id=trace_id,
            )
            return _mutation_body(result, trace_id=trace_id)

        result = await services.control.transition_memory(
            memory_id=parts[2],
            action=_lifecycle_action(parts[3]),
            scope=scope,
            actor_id=envelope.actor_id,
            reason=envelope.reason,
            idempotency_key=envelope.idempotency_key,
            trace_id=trace_id,
        )
        return _mutation_body(result, trace_id=trace_id)

    if method == "PATCH" and len(parts) == 4 and parts[:3] == ("v1", "control", "pages"):
        result = await services.control.edit_page(
            page_id=parts[3],
            scope=scope,
            title=_required_body_text(payload, "title"),
            brief=_required_body_text(payload, "brief"),
            actor_id=envelope.actor_id,
            reason=envelope.reason,
            idempotency_key=envelope.idempotency_key,
            trace_id=trace_id,
        )
        return _mutation_body(result, trace_id=trace_id)

    if method == "POST" and len(parts) == 5 and parts[:3] == ("v1", "control", "pages"):
        if parts[4] == "rebuild":
            result = await services.control.rebuild_page(
                page_id=parts[3],
                scope=scope,
                actor_id=envelope.actor_id,
                reason=envelope.reason,
                idempotency_key=envelope.idempotency_key,
                trace_id=trace_id,
            )
            return _mutation_body(result, trace_id=trace_id)
        if parts[4] == "restore-version":
            result = await services.control.restore_page_version(
                page_id=parts[3],
                version=_required_body_int(payload, "version"),
                scope=scope,
                actor_id=envelope.actor_id,
                reason=envelope.reason,
                idempotency_key=envelope.idempotency_key,
                trace_id=trace_id,
            )
            return _mutation_body(result, trace_id=trace_id)

    if method == "POST" and len(parts) == 5 and parts[:3] == ("v1", "control", "push-candidates"):
        if parts[4] == "approve":
            result = await services.control.approve_push_candidate(
                candidate_id=parts[3],
                scope=scope,
                actor_id=envelope.actor_id,
                reason=envelope.reason,
                idempotency_key=envelope.idempotency_key,
                trace_id=trace_id,
            )
            return _mutation_body(result, trace_id=trace_id)
        if parts[4] == "skip":
            result = await services.control.skip_push_candidate(
                candidate_id=parts[3],
                scope=scope,
                actor_id=envelope.actor_id,
                reason=envelope.reason,
                idempotency_key=envelope.idempotency_key,
                trace_id=trace_id,
            )
            return _mutation_body(result, trace_id=trace_id)

    if (
        method == "POST"
        and len(parts) == 5
        and parts[:3] == ("v1", "control", "jobs")
        and parts[4] == "retry"
    ):
        result = await services.control.retry_job(
            job_id=parts[3],
            kind=_required_body_text(payload, "kind"),
            scope=scope,
            actor_id=envelope.actor_id,
            reason=envelope.reason,
            idempotency_key=envelope.idempotency_key,
            trace_id=trace_id,
        )
        return _mutation_body(result, trace_id=trace_id)

    if (
        method == "POST"
        and len(parts) == 4
        and parts[:2] == ("v1", "source-events")
        and parts[3] == "purge"
    ):
        if services.source_redaction is None:
            raise ValidationFailure(
                "source_redaction_unavailable",
                "Source redaction service is not configured.",
            )
        result = await services.source_redaction.purge_source(
            SourceRedactionCommand(
                source_event_id=parts[2],
                scope=scope,
                actor_id=envelope.actor_id,
                reason=envelope.reason,
                idempotency_key=envelope.idempotency_key,
                trace_id=trace_id,
                purge_level=_required_body_text(payload, "purge_level"),
            )
        )
        return _mutation_body(result, trace_id=trace_id)

    if (
        method == "POST"
        and len(parts) == 6
        and parts[:2] == ("v1", "platforms")
        and parts[3] == "push-candidates"
        and parts[5] == "send"
    ):
        result = await services.control.send_push_candidate(
            candidate_id=parts[4],
            platform=parts[2],
            scope=scope,
            actor_id=envelope.actor_id,
            reason=envelope.reason,
            idempotency_key=envelope.idempotency_key,
            trace_id=trace_id,
        )
        return _mutation_body(result, trace_id=trace_id)

    raise ValidationFailure("route_not_found", "route not found")


async def _scope_from_query(
    query: Mapping[str, str],
    resolver: ScopeResolver,
):
    resolved = await resolver.resolve_control(
        MemoryScope(
            project_memory_space_id=_required_query_text(query, "project_memory_space_id"),
            group_id=_optional_query_text(query, "group_id"),
            thread_id=_optional_query_text(query, "thread_id"),
            shared_group_id=_optional_query_text(query, "shared_group_id"),
        )
    )
    return resolved.effective_scope


def _mutation_envelope(payload: Mapping[str, object]) -> MutationEnvelope:
    return MutationEnvelope(
        actor_id=require_text(payload.get("actor_id"), "actor_id"),
        reason=require_text(payload.get("reason"), "reason"),
        idempotency_key=require_text(payload.get("idempotency_key"), "idempotency_key"),
        trace_id=_optional_body_text(payload, "trace_id"),
    )


def _mutation_body(item: object, *, trace_id: str) -> JsonObject:
    return json_object({"ok": True, "item": item, "trace_id": trace_id})


def _lifecycle_action(value: str) -> LifecycleAction:
    try:
        return LifecycleAction(value)
    except ValueError as exc:
        raise ValidationFailure("lifecycle_action_invalid", "Lifecycle action is not supported.") from exc


def _required_query_text(query: Mapping[str, str], field: str) -> str:
    return require_text(query.get(field), field)


def _optional_query_text(query: Mapping[str, str], field: str) -> str | None:
    value = query.get(field)
    if value is None or not value.strip():
        return None
    return require_text(value, field)


def _trace_id_from_query(query: Mapping[str, str], prefix: str) -> str:
    return _optional_query_text(query, "trace_id") or f"{prefix}:{uuid.uuid4()}"


def _limit_from_query(query: Mapping[str, str]) -> int:
    raw = query.get("limit")
    if raw is None or not raw.strip():
        return 50
    if not raw.isdecimal():
        raise ValidationFailure("control_limit_invalid", "Control Plane limit must be an integer.")
    return int(raw)


def _required_body_text(payload: Mapping[str, object], field: str) -> str:
    return require_text(payload.get(field), field)


def _optional_body_text(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    return require_text(value, field)


def _required_body_int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field} must be an integer")
    return value


def _generated_trace_id(path: str) -> str:
    return f"control:mutation:{path.strip('/').replace('/', ':')}:{uuid.uuid4()}"


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.split("/") if part)


def _success_status(method: str, path: str) -> int:
    if method.upper() == "POST" and "/events/" in path:
        return 202
    return 200


def _http_status_override(exc: MemWingFailure, status_code: int) -> int:
    if isinstance(exc, ValidationFailure) and exc.reason_code == "route_not_found":
        return 404
    if isinstance(exc, ValidationFailure) and exc.reason_code == "method_not_allowed":
        return 405
    return status_code
