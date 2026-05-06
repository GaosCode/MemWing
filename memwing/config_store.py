from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any


PROFILE_VALUES = frozenset(("lite", "full-local", "production"))


class ConfigStoreError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConfigPaths:
    user_config: Path
    project_config: Path | None


def default_memwing_home(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    configured = source.get("MEMWING_HOME")
    if configured is not None and configured.strip():
        return Path(configured).expanduser()
    return Path.home() / ".memwing"


def default_user_config_path(env: Mapping[str, str] | None = None) -> Path:
    return default_memwing_home(env) / "memwing.json"


def default_project_config_path(cwd: Path | None = None) -> Path:
    root = Path.cwd() if cwd is None else cwd
    return root / ".memwing" / "memwing.json"


def resolve_config_paths(
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ConfigPaths:
    project_config = default_project_config_path(cwd)
    return ConfigPaths(
        user_config=default_user_config_path(env),
        project_config=project_config if project_config.exists() else None,
    )


def load_user_config(path: Path | None = None) -> dict[str, Any]:
    return load_json_config(default_user_config_path() if path is None else path)


def load_effective_config(
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    paths = resolve_config_paths(cwd=cwd, env=env)
    config = default_config()
    _deep_merge(config, load_json_config(paths.user_config))
    if paths.project_config is not None:
        _deep_merge(config, load_json_config(paths.project_config))
    _deep_merge(config, _env_config(env))
    _validate_config(config)
    return config


def load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigStoreError(f"MemWing config is not valid JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise ConfigStoreError(f"MemWing config must be a JSON object: {path}")
    return raw


def write_user_config(config: Mapping[str, Any], path: Path | None = None) -> Path:
    target = default_user_config_path() if path is None else path
    _validate_config(config)
    _atomic_write_json(target, dict(config))
    return target


def default_config() -> dict[str, Any]:
    return {
        "profile": "lite",
        "api": {
            "host": "127.0.0.1",
            "port": 8000,
        },
        "runtime": {
            "storageBackend": "sqlite",
            "modelRuntime": "openclaw",
            "modelTransport": "local",
            "modelTimeoutSeconds": 60,
        },
        "database": {},
        "graph": {
            "backend": "disabled",
        },
        "evidence": {
            "backend": "disabled",
        },
        "scope": {
            "defaultProject": "project_001",
        },
        "openclaw": {
            "workspaceId": "workspace_001",
        },
    }


def get_config_value(config: Mapping[str, Any], dotted_key: str) -> Any:
    current: Any = config
    for part in _key_parts(dotted_key):
        if not isinstance(current, Mapping) or part not in current:
            raise ConfigStoreError(f"config key is not set: {dotted_key}")
        current = current[part]
    return current


def set_config_value(config: MutableMapping[str, Any], dotted_key: str, value: Any) -> None:
    parts = _key_parts(dotted_key)
    current: MutableMapping[str, Any] = config
    for part in parts[:-1]:
        existing = current.get(part)
        if existing is None:
            child: dict[str, Any] = {}
            current[part] = child
            current = child
            continue
        if not isinstance(existing, MutableMapping):
            raise ConfigStoreError(f"config key cannot contain children: {part}")
        current = existing
    current[parts[-1]] = value
    _validate_config(config)


def unset_config_value(config: MutableMapping[str, Any], dotted_key: str) -> None:
    parts = _key_parts(dotted_key)
    current: MutableMapping[str, Any] = config
    for part in parts[:-1]:
        existing = current.get(part)
        if not isinstance(existing, MutableMapping):
            raise ConfigStoreError(f"config key is not set: {dotted_key}")
        current = existing
    if parts[-1] not in current:
        raise ConfigStoreError(f"config key is not set: {dotted_key}")
    del current[parts[-1]]
    _validate_config(config)


def parse_config_value(raw_value: str) -> Any:
    text = raw_value.strip()
    if text.casefold() == "true":
        return True
    if text.casefold() == "false":
        return False
    if text.casefold() == "null":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    if text.startswith(("{", "[", '"')):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return raw_value
    return raw_value


def _env_config(env: Mapping[str, str] | None) -> dict[str, Any]:
    source = os.environ if env is None else env
    config: dict[str, Any] = {}
    _set_if_present(config, "profile", source.get("MEMWING_PROFILE"))
    _set_if_present(config, "database.url", source.get("DATABASE_URL"))
    _set_if_present(config, "api.host", source.get("MEMWING_API_HOST"))
    _set_if_present(config, "api.port", source.get("MEMWING_API_PORT"))
    _set_if_present(config, "runtime.storageBackend", source.get("MEMWING_STORAGE_BACKEND"))
    _set_if_present(config, "runtime.modelRuntime", source.get("MEMWING_MODEL_RUNTIME"))
    _set_if_present(config, "runtime.modelTransport", source.get("MEMWING_MODEL_TRANSPORT"))
    _set_if_present(
        config,
        "runtime.modelTimeoutSeconds",
        source.get("MEMWING_MODEL_TIMEOUT_SECONDS"),
    )
    _set_if_present(config, "graph.backend", source.get("MEMWING_GRAPH_BACKEND"))
    _set_if_present(config, "graph.neo4j.uri", source.get("MEMWING_GRAPHITI_NEO4J_URI"))
    _set_if_present(config, "graph.neo4j.user", source.get("MEMWING_GRAPHITI_NEO4J_USER"))
    _set_if_present(
        config,
        "graph.neo4j.password",
        source.get("MEMWING_GRAPHITI_NEO4J_PASSWORD"),
    )
    _set_if_present(config, "evidence.backend", source.get("MEMWING_EVIDENCE_BACKEND"))
    _set_if_present(config, "evidence.qdrant.url", source.get("MEMWING_QDRANT_URL"))
    _set_if_present(config, "evidence.qdrant.apiKey", source.get("MEMWING_QDRANT_API_KEY"))
    _set_if_present(
        config,
        "scope.defaultProject",
        source.get("MEMWING_DEFAULT_PROJECT_MEMORY_SPACE_ID"),
    )
    _set_if_present(config, "openclaw.workspaceId", source.get("MEMWING_OPENCLAW_WORKSPACE_ID"))
    return config


def _set_if_present(config: MutableMapping[str, Any], dotted_key: str, value: str | None) -> None:
    if value is None or not value.strip():
        return
    set_config_value(config, dotted_key, parse_config_value(value))


def _atomic_write_json(path: Path, config: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _deep_merge(target: MutableMapping[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        existing = target.get(key)
        if isinstance(existing, MutableMapping) and isinstance(value, Mapping):
            _deep_merge(existing, value)
        else:
            target[key] = value


def _key_parts(dotted_key: str) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in dotted_key.split(".") if part.strip())
    if not parts:
        raise ConfigStoreError("config key is required")
    return parts


def _validate_config(config: Mapping[str, Any]) -> None:
    profile = config.get("profile")
    if profile is not None and profile not in PROFILE_VALUES:
        raise ConfigStoreError("profile must be lite, full-local, or production")
    api = config.get("api")
    if isinstance(api, Mapping) and "port" in api:
        try:
            port = int(api["port"])
        except (TypeError, ValueError) as exc:
            raise ConfigStoreError("api.port must be an integer") from exc
        if port <= 0 or port > 65535:
            raise ConfigStoreError("api.port must be between 1 and 65535")
