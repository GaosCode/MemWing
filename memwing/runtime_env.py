from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from memwing.config_store import default_memwing_home, get_config_value


SECRET_NAMES = frozenset(("PASSWORD", "SECRET", "TOKEN", "API_KEY", "KEY"))


@dataclass(frozen=True, slots=True)
class RuntimeEnv:
    profile: str
    env: dict[str, str]

    def redacted(self) -> dict[str, str]:
        return redact_env(self.env)


def build_runtime_env(
    config: Mapping[str, Any],
    *,
    base_env: Mapping[str, str] | None = None,
) -> RuntimeEnv:
    source = dict(os.environ if base_env is None else base_env)
    profile = str(config.get("profile") or "lite")
    env = dict(source)
    env["MEMWING_PROFILE"] = profile
    _set(env, "MEMWING_API_HOST", _optional(config, "api.host"))
    _set(env, "MEMWING_API_PORT", _optional(config, "api.port"))
    _set(env, "MEMWING_MODEL_RUNTIME", _optional(config, "runtime.modelRuntime"))
    _set(env, "MEMWING_MODEL_TRANSPORT", _optional(config, "runtime.modelTransport"))
    _set(env, "MEMWING_MODEL_TIMEOUT_SECONDS", _optional(config, "runtime.modelTimeoutSeconds"))
    _set(env, "MEMWING_DEFAULT_PROJECT_MEMORY_SPACE_ID", _optional(config, "scope.defaultProject"))
    _set(env, "MEMWING_OPENCLAW_WORKSPACE_ID", _optional(config, "openclaw.workspaceId"))

    if profile == "lite":
        _apply_lite_env(config, env)
    else:
        _set(env, "DATABASE_URL", _optional(config, "database.url"))
        _set(env, "MEMWING_STORAGE_BACKEND", _optional(config, "runtime.storageBackend"))
        _set(env, "MEMWING_GRAPH_BACKEND", _optional(config, "graph.backend"))
        _set(env, "MEMWING_EVIDENCE_BACKEND", _optional(config, "evidence.backend"))

    _set(env, "MEMWING_GRAPHITI_NEO4J_URI", _optional(config, "graph.neo4j.uri"))
    _set(env, "MEMWING_GRAPHITI_NEO4J_USER", _optional(config, "graph.neo4j.user"))
    _set(env, "MEMWING_GRAPHITI_NEO4J_PASSWORD", _optional(config, "graph.neo4j.password"))
    _set(env, "MEMWING_QDRANT_URL", _optional(config, "evidence.qdrant.url"))
    _set(env, "QDRANT_URL", _optional(config, "evidence.qdrant.url"))
    _set(env, "MEMWING_QDRANT_API_KEY", _optional(config, "evidence.qdrant.apiKey"))
    _set(env, "QDRANT_API_KEY", _optional(config, "evidence.qdrant.apiKey"))
    return RuntimeEnv(profile=profile, env=env)


def redact_env(env: Mapping[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in sorted(env.items()):
        if _is_secret_name(key):
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def _apply_lite_env(config: Mapping[str, Any], env: dict[str, str]) -> None:
    memwing_home = default_memwing_home(env)
    sqlite_path = _optional(config, "runtime.sqlitePath") or str(memwing_home / "memwing.db")
    env["MEMWING_STORAGE_BACKEND"] = "sqlite"
    env["MEMWING_LITE_DB_PATH"] = str(Path(sqlite_path).expanduser())
    env["MEMWING_GRAPH_BACKEND"] = "disabled"
    env["MEMWING_EVIDENCE_BACKEND"] = "disabled"
    env.pop("DATABASE_URL", None)


def _optional(config: Mapping[str, Any], dotted_key: str) -> str | None:
    try:
        value = get_config_value(config, dotted_key)
    except ValueError:
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _set(env: dict[str, str], name: str, value: str | None) -> None:
    if value is not None:
        env[name] = value


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in SECRET_NAMES)
