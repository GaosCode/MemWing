from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from urllib.parse import unquote

from memwing.api.memwing_tools import (
    memwing_explain_memory,
    memwing_get_memory,
    memwing_get_project_context,
    memwing_search_memory,
    memwing_search_sources,
)
from memwing.api.openclaw_memory import (
    native_memory_get,
    native_memory_index,
    native_memory_search,
    native_memory_status,
)
from memwing.api.openclaw_runtime import (
    OpenClawRuntimeUnavailableError,
    assemble_openclaw_context,
    complete_openclaw_turn,
    ingest_openclaw_event,
    observe_openclaw_hook,
)
from memwing.api.types import JsonObject, JsonValue
from memwing.api.validation import SchemaValidationError
from memwing.application.scope_resolver import ScopeResolutionError
from memwing.ports.agent_runtime import AgentRuntimePort


@dataclass(frozen=True, slots=True)
class OpenClawHttpResponse:
    status_code: int
    body: JsonObject


async def handle_openclaw_http_request(
    *,
    method: str,
    path: str,
    payload: Mapping[str, object],
    runtime: AgentRuntimePort,
) -> OpenClawHttpResponse:
    if method.upper() != "POST":
        return OpenClawHttpResponse(
            status_code=405,
            body={"ok": False, "code": "method_not_allowed", "message": "method not allowed"},
        )

    try:
        return await _dispatch_post(path=path, payload=payload, runtime=runtime)
    except SchemaValidationError as exc:
        return OpenClawHttpResponse(
            status_code=400,
            body={"ok": False, "code": "schema_invalid", "message": str(exc)},
        )
    except OpenClawRuntimeUnavailableError as exc:
        return OpenClawHttpResponse(
            status_code=503,
            body={"ok": False, "code": "openclaw_runtime_unavailable", "message": str(exc)},
        )
    except ScopeResolutionError as exc:
        return OpenClawHttpResponse(
            status_code=403,
            body={"ok": False, "code": "scope_resolution_failed", "message": str(exc)},
        )


async def _dispatch_post(
    *,
    path: str,
    payload: Mapping[str, object],
    runtime: AgentRuntimePort,
) -> OpenClawHttpResponse:
    if path == "/v1/openclaw/context/assemble":
        result = await assemble_openclaw_context(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))
    if path == "/v1/openclaw/events/ingest":
        result = await ingest_openclaw_event(payload, runtime)
        return OpenClawHttpResponse(status_code=202, body=_json_object(result))
    if path == "/v1/openclaw/events/after-turn":
        result = await complete_openclaw_turn(payload, runtime)
        return OpenClawHttpResponse(status_code=202, body=_json_object(result))
    if path.startswith("/v1/openclaw/hooks/"):
        hook_name = unquote(path.removeprefix("/v1/openclaw/hooks/"))
        result = await observe_openclaw_hook({**payload, "hook_name": hook_name}, runtime)
        return OpenClawHttpResponse(status_code=202, body=_json_object(result))

    if path in ("/v1/memwing/tools/search-memory", "/v1/tools/memwing/search-memory"):
        result = await memwing_search_memory(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))
    if path in ("/v1/memwing/tools/get-memory", "/v1/tools/memwing/get-memory"):
        result = await memwing_get_memory(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))
    if path in ("/v1/memwing/tools/explain-memory", "/v1/tools/memwing/explain-memory"):
        result = await memwing_explain_memory(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))
    if path in ("/v1/memwing/tools/search-sources", "/v1/tools/memwing/search-sources"):
        result = await memwing_search_sources(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))
    if path in ("/v1/memwing/tools/project-context", "/v1/tools/memwing/get-project-context"):
        result = await memwing_get_project_context(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))

    if path == "/v1/openclaw/native/memory-search":
        result = await native_memory_search(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))
    if path == "/v1/openclaw/native/memory-get":
        result = await native_memory_get(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))
    if path == "/v1/openclaw/native/memory-index":
        result = await native_memory_index(payload)
        return OpenClawHttpResponse(status_code=202, body=_json_object(result))
    if path == "/v1/openclaw/native/memory-status":
        result = await native_memory_status(payload, runtime)
        return OpenClawHttpResponse(status_code=200, body=_json_object(result))

    return OpenClawHttpResponse(
        status_code=404,
        body={"ok": False, "code": "route_not_found", "message": "route not found"},
    )


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
