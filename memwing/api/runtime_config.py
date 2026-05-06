from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from memwing.api.openclaw_mock_runtime import OpenClawMockRuntime
from memwing.ports.agent_runtime import AgentRuntimePort


class OpenClawRuntimeUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FeishuPushConfig:
    app_id: str
    app_secret: str
    receive_id_type: str
    api_base_url: str
    timeout_seconds: float


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


def graphiti_semantic_bulk_enabled_from_env(env: Mapping[str, str] | None = None) -> bool:
    value = _optional_env(env, "MEMWING_GRAPHITI_SEMANTIC_BULK_ENABLED")
    return value is not None and value.casefold() == "true"


def graph_write_timeout_seconds_from_env(env: Mapping[str, str] | None = None) -> float:
    raw_value = _optional_env(env, "MEMWING_GRAPH_WRITE_TIMEOUT_SECONDS") or "900"
    try:
        timeout_seconds = float(raw_value)
    except ValueError as exc:
        raise OpenClawRuntimeUnavailableError(
            "MEMWING_GRAPH_WRITE_TIMEOUT_SECONDS must be a positive number"
        ) from exc
    if timeout_seconds <= 0:
        raise OpenClawRuntimeUnavailableError(
            "MEMWING_GRAPH_WRITE_TIMEOUT_SECONDS must be a positive number"
        )
    return timeout_seconds


def graph_write_batch_size_from_env(env: Mapping[str, str] | None = None) -> int:
    return _positive_int_env(env, "MEMWING_GRAPH_WRITE_BATCH_SIZE", "1")


def graph_write_max_project_concurrency_from_env(env: Mapping[str, str] | None = None) -> int:
    return _positive_int_env(env, "MEMWING_GRAPH_WRITE_MAX_PROJECT_CONCURRENCY", "1")


def graph_write_max_global_concurrency_from_env(env: Mapping[str, str] | None = None) -> int:
    return _positive_int_env(env, "MEMWING_GRAPH_WRITE_MAX_GLOBAL_CONCURRENCY", "16")


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


def feishu_push_config_from_env(env: Mapping[str, str] | None = None) -> FeishuPushConfig | None:
    enabled = _optional_env(env, "MEMWING_FEISHU_PUSH_ENABLED")
    if enabled is None or enabled.casefold() != "true":
        return None

    app_id = _required_env(env, "MEMWING_FEISHU_APP_ID")
    app_secret = _required_env(env, "MEMWING_FEISHU_APP_SECRET")
    receive_id_type = _optional_env(env, "MEMWING_FEISHU_RECEIVE_ID_TYPE") or "chat_id"
    if receive_id_type not in {"open_id", "user_id", "union_id", "email", "chat_id"}:
        raise OpenClawRuntimeUnavailableError(
            "MEMWING_FEISHU_RECEIVE_ID_TYPE must be open_id, user_id, union_id, email, or chat_id"
        )
    timeout_seconds = _positive_float_env(env, "MEMWING_FEISHU_TIMEOUT_SECONDS", "10")
    return FeishuPushConfig(
        app_id=app_id,
        app_secret=app_secret,
        receive_id_type=receive_id_type,
        api_base_url=_optional_env(env, "MEMWING_FEISHU_API_BASE_URL")
        or "https://open.feishu.cn/open-apis",
        timeout_seconds=timeout_seconds,
    )


def _required_env(env: Mapping[str, str] | None, name: str) -> str:
    value = _optional_env(env, name)
    if value is None:
        raise OpenClawRuntimeUnavailableError(f"{name} is required when Feishu push is enabled")
    return value


def _positive_float_env(env: Mapping[str, str] | None, name: str, default: str) -> float:
    raw_value = _optional_env(env, name) or default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise OpenClawRuntimeUnavailableError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise OpenClawRuntimeUnavailableError(f"{name} must be a positive number")
    return value


def _positive_int_env(env: Mapping[str, str] | None, name: str, default: str) -> int:
    raw_value = _optional_env(env, name) or default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise OpenClawRuntimeUnavailableError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise OpenClawRuntimeUnavailableError(f"{name} must be a positive integer")
    return value


def _optional_env(env: Mapping[str, str] | None, name: str) -> str | None:
    source = os.environ if env is None else env
    value = source.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()
