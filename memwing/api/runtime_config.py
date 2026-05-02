from __future__ import annotations

from collections.abc import Mapping
import os

from memwing.api.openclaw_mock_runtime import OpenClawMockRuntime
from memwing.ports.agent_runtime import AgentRuntimePort


class OpenClawRuntimeUnavailableError(RuntimeError):
    pass


def resolve_openclaw_runtime(
    runtime: AgentRuntimePort | None,
    *,
    allow_mock_runtime: bool = False,
) -> AgentRuntimePort:
    if runtime is not None:
        return runtime
    if allow_mock_runtime:
        return OpenClawMockRuntime()
    raise OpenClawRuntimeUnavailableError("OpenClaw runtime is not configured")


def database_url_from_env(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    database_url = source.get("DATABASE_URL", "").strip()
    if not database_url:
        raise OpenClawRuntimeUnavailableError("DATABASE_URL is required for Postgres OpenClaw runtime")
    return database_url


def graph_backend_from_env(env: Mapping[str, str] | None = None) -> str:
    backend = _optional_env(env, "MEMWING_GRAPH_BACKEND") or "disabled"
    if backend not in {"disabled", "graphiti"}:
        raise OpenClawRuntimeUnavailableError("MEMWING_GRAPH_BACKEND must be disabled or graphiti")
    return backend


def graphiti_neo4j_uri_from_env(env: Mapping[str, str] | None = None) -> str:
    return _optional_env(env, "MEMWING_GRAPHITI_NEO4J_URI") or "bolt://localhost:7687"


def graphiti_neo4j_user_from_env(env: Mapping[str, str] | None = None) -> str | None:
    return _optional_env(env, "MEMWING_GRAPHITI_NEO4J_USER") or "neo4j"


def graphiti_neo4j_password_from_env(env: Mapping[str, str] | None = None) -> str | None:
    return _optional_env(env, "MEMWING_GRAPHITI_NEO4J_PASSWORD")


def evidence_backend_from_env(env: Mapping[str, str] | None = None) -> str:
    backend = _optional_env(env, "MEMWING_EVIDENCE_BACKEND") or "disabled"
    if backend not in {"disabled", "qdrant"}:
        raise OpenClawRuntimeUnavailableError("MEMWING_EVIDENCE_BACKEND must be disabled or qdrant")
    return backend


def qdrant_url_from_env(env: Mapping[str, str] | None = None) -> str:
    return _optional_env(env, "QDRANT_URL") or "http://127.0.0.1:6333"


def qdrant_api_key_from_env(env: Mapping[str, str] | None = None) -> str | None:
    return _optional_env(env, "QDRANT_API_KEY")


def qdrant_collection_from_env(env: Mapping[str, str] | None = None) -> str:
    return _optional_env(env, "QDRANT_COLLECTION") or "memwing_evidence"


def evidence_vector_size_from_env(env: Mapping[str, str] | None = None) -> int:
    raw_value = _optional_env(env, "MEMWING_EVIDENCE_VECTOR_SIZE") or "1536"
    try:
        vector_size = int(raw_value)
    except ValueError as exc:
        raise OpenClawRuntimeUnavailableError(
            "MEMWING_EVIDENCE_VECTOR_SIZE must be a positive integer"
        ) from exc
    if vector_size <= 0:
        raise OpenClawRuntimeUnavailableError(
            "MEMWING_EVIDENCE_VECTOR_SIZE must be a positive integer"
        )
    return vector_size


def benchmark_admin_enabled_from_env(env: Mapping[str, str] | None = None) -> bool:
    value = _optional_env(env, "MEMWING_BENCHMARK_ADMIN_ENABLED")
    return value is not None and value.casefold() == "true"


def _optional_env(env: Mapping[str, str] | None, name: str) -> str | None:
    source = os.environ if env is None else env
    value = source.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()
