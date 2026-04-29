from __future__ import annotations

from collections.abc import Mapping

from memwing.api.agent_context import AgentContextRequest, AgentContextResult
from memwing.api.agent_knowledge import (
    AgentKnowledgeExplainRequest,
    AgentKnowledgeExplainResult,
    AgentKnowledgeGetRequest,
    AgentKnowledgeGetResult,
)
from memwing.api.agent_memory import AgentMemoryQuery, AgentMemorySearchResult
from memwing.api.openclaw_payloads import (
    memory_scope_from_payload,
    openclaw_runtime_ref_from_payload,
)
from memwing.api.runtime_config import resolve_openclaw_runtime
from memwing.api.validation import SchemaValidationError, require_positive_int, require_text
from memwing.ports.agent_runtime import AgentRuntimePort


MEMWING_TOOL_NAMES = (
    "memwing_search_memory",
    "memwing_get_memory",
    "memwing_explain_memory",
    "memwing_search_sources",
    "memwing_get_project_context",
)

_MEMORY_QUERY_FIELDS = frozenset(
    (
        "agent_id",
        "workspace_id",
        "session_id",
        "query",
        "mode",
        "limit",
        "cursor",
        "sort",
        "min_score",
        "scope",
    )
)
_MEMORY_GET_FIELDS = frozenset(
    (
        "agent_id",
        "workspace_id",
        "session_id",
        "memory_id",
        "include_evidence",
        "scope",
    )
)
_MEMORY_EXPLAIN_FIELDS = frozenset(
    (
        "agent_id",
        "workspace_id",
        "session_id",
        "memory_id",
        "scope",
    )
)
_PROJECT_CONTEXT_FIELDS = frozenset(
    (
        "agent_id",
        "workspace_id",
        "session_id",
        "token_budget",
        "scope",
    )
)


async def memwing_search_memory(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
    *,
    allow_mock_runtime: bool = False,
) -> AgentMemorySearchResult:
    return await resolve_openclaw_runtime(
        runtime,
        allow_mock_runtime=allow_mock_runtime,
    ).knowledge_search(_memory_query_from_payload(payload))


async def memwing_get_memory(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
    *,
    allow_mock_runtime: bool = False,
) -> AgentKnowledgeGetResult:
    _reject_unknown_fields(payload, _MEMORY_GET_FIELDS)
    request = AgentKnowledgeGetRequest(
        runtime_ref=openclaw_runtime_ref_from_payload(payload),
        memory_id=_required_text(payload.get("memory_id"), "memory_id"),
        include_evidence=_include_evidence(payload.get("include_evidence")),
        scope=memory_scope_from_payload(payload),
    )
    return await resolve_openclaw_runtime(
        runtime,
        allow_mock_runtime=allow_mock_runtime,
    ).knowledge_get(request)


async def memwing_explain_memory(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
    *,
    allow_mock_runtime: bool = False,
) -> AgentKnowledgeExplainResult:
    _reject_unknown_fields(payload, _MEMORY_EXPLAIN_FIELDS)
    request = AgentKnowledgeExplainRequest(
        runtime_ref=openclaw_runtime_ref_from_payload(payload),
        memory_id=_required_text(payload.get("memory_id"), "memory_id"),
        scope=memory_scope_from_payload(payload),
    )
    return await resolve_openclaw_runtime(
        runtime,
        allow_mock_runtime=allow_mock_runtime,
    ).knowledge_explain(request)


async def memwing_search_sources(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
    *,
    allow_mock_runtime: bool = False,
) -> AgentMemorySearchResult:
    query = _memory_query_from_payload(payload, default_mode="history")
    return await resolve_openclaw_runtime(
        runtime,
        allow_mock_runtime=allow_mock_runtime,
    ).knowledge_search(query)


async def memwing_get_project_context(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
    *,
    allow_mock_runtime: bool = False,
) -> AgentContextResult:
    _reject_unknown_fields(payload, _PROJECT_CONTEXT_FIELDS)
    request = AgentContextRequest(
        runtime_ref=openclaw_runtime_ref_from_payload(payload),
        scope=memory_scope_from_payload(payload),
        prompt=None,
        messages=(),
        token_budget=_optional_positive_int(payload.get("token_budget"), "token_budget"),
        available_tools=MEMWING_TOOL_NAMES,
    )
    return await resolve_openclaw_runtime(
        runtime,
        allow_mock_runtime=allow_mock_runtime,
    ).build_context(request)


def _memory_query_from_payload(
    payload: Mapping[str, object],
    *,
    default_mode: str = "current",
) -> AgentMemoryQuery:
    _reject_unknown_fields(payload, _MEMORY_QUERY_FIELDS)
    return AgentMemoryQuery(
        runtime_ref=openclaw_runtime_ref_from_payload(payload),
        query=_required_text(payload.get("query"), "query"),
        scope=memory_scope_from_payload(payload),
        mode=_mode(payload.get("mode"), default_mode),
        limit=_optional_positive_int(payload.get("limit"), "limit") or 20,
        cursor=_cursor(payload.get("cursor")),
        sort=_sort(payload.get("sort")),
        min_score=_min_score(payload.get("min_score")),
    )


def _reject_unknown_fields(payload: Mapping[str, object], allowed_fields: frozenset[str]) -> None:
    for field_name in payload:
        if field_name not in allowed_fields:
            raise SchemaValidationError(f"{field_name} is not supported")


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


def _mode(value: object, default: str) -> str:
    if value is None:
        return default
    if value not in ("current", "history"):
        raise SchemaValidationError("mode must be current or history")
    return value


def _sort(value: object) -> str:
    if value is None:
        return "relevance"
    if value not in ("relevance", "event_time", "updated_at"):
        raise SchemaValidationError("sort must be relevance, event_time, or updated_at")
    return value


def _cursor(value: object) -> str | None:
    if value is None:
        return None
    return _required_text(value, "cursor")


def _min_score(value: object) -> float:
    if value is None:
        return 0
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise SchemaValidationError("min_score must be a non-negative number")
    return float(value)


def _include_evidence(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise SchemaValidationError("include_evidence must be a boolean")
    return value
