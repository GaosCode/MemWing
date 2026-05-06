from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from memwing.config_store import default_config, set_config_value


PROFILE_VALUES = ("lite", "full-local", "production")


def build_profile_config(profile: str, base_config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = default_config()
    if base_config is not None:
        _merge(config, base_config)
    apply_profile_template(config, profile)
    return config


def apply_profile_template(config: MutableMapping[str, Any], profile: str) -> None:
    if profile not in PROFILE_VALUES:
        raise ValueError("profile must be lite, full-local, or production")
    set_config_value(config, "profile", profile)
    _set_default(config, "runtime.modelRuntime", "openclaw")
    _set_default(config, "runtime.modelTransport", "local")

    if profile == "lite":
        set_config_value(config, "runtime.storageBackend", "sqlite")
        set_config_value(config, "graph.backend", "disabled")
        set_config_value(config, "evidence.backend", "disabled")
        return

    set_config_value(config, "runtime.storageBackend", "postgres")
    set_config_value(config, "graph.backend", "graphiti")
    set_config_value(config, "evidence.backend", "qdrant")

    if profile == "full-local":
        _set_default(config, "database.url", "postgresql://memwing@127.0.0.1:5432/memwing")
        _set_default(config, "graph.neo4j.uri", "bolt://127.0.0.1:7687")
        _set_default(config, "graph.neo4j.user", "neo4j")
        _set_default(config, "evidence.qdrant.url", "http://127.0.0.1:6333")


def _set_default(config: MutableMapping[str, Any], dotted_key: str, value: Any) -> None:
    current: Any = config
    parts = tuple(part for part in dotted_key.split(".") if part)
    for part in parts[:-1]:
        if not isinstance(current, MutableMapping):
            return
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        current = child
    if isinstance(current, MutableMapping) and not current.get(parts[-1]):
        set_config_value(config, dotted_key, value)


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(target.get(key), dict) and isinstance(value, dict):
            _merge(target[key], value)
        else:
            target[key] = value
