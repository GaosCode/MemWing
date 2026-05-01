from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from memwing.ports.model_runtime import (
    MEMWING_MODEL_ROLES,
    MemWingModelRole,
    MemWingModelRuntime,
    MemWingModelSelection,
    MemWingModelTransport,
)


_ROLE_ENV_SUFFIXES: Mapping[MemWingModelRole, str] = {
    "page_memory": "PAGE_MEMORY",
    "long_term_filter": "LONG_TERM_FILTER",
    "graphiti_extraction": "GRAPHITI_EXTRACTION",
    "graphiti_embedding": "GRAPHITI_EMBEDDING",
    "graphiti_rerank": "GRAPHITI_RERANK",
}

_PLUGIN_MODEL_KEYS: Mapping[str, MemWingModelRole] = {
    "pageMemory": "page_memory",
    "longTermFilter": "long_term_filter",
    "graphitiExtraction": "graphiti_extraction",
    "graphitiEmbedding": "graphiti_embedding",
    "graphitiRerank": "graphiti_rerank",
}


@dataclass(frozen=True, slots=True)
class MemWingModelConfigResolver:
    runtime: MemWingModelRuntime
    role_models: Mapping[MemWingModelRole, str]
    default_model: str | None
    transport: MemWingModelTransport | None
    timeout_seconds: float

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> MemWingModelConfigResolver:
        values = os.environ if env is None else env
        runtime = _runtime(
            _optional_text(values.get("MEMWING_MODEL_RUNTIME"))
            or _optional_text(values.get("MEMWING_LLM_RUNTIME"))
            or "test"
        )
        role_models = {
            role: model
            for role in MEMWING_MODEL_ROLES
            if (model := _optional_text(values.get(f"MEMWING_MODEL_{_ROLE_ENV_SUFFIXES[role]}")))
            is not None
        }
        return cls(
            runtime=runtime,
            role_models=role_models,
            default_model=_default_model(values, runtime),
            transport=_transport(
                _optional_text(values.get("MEMWING_MODEL_TRANSPORT"))
                or _optional_text(values.get("MEMWING_OPENCLAW_TRANSPORT"))
            ),
            timeout_seconds=_positive_float(
                _optional_text(values.get("MEMWING_MODEL_TIMEOUT_SECONDS"))
                or _optional_text(values.get("MEMWING_LLM_TIMEOUT_SECONDS"))
                or _optional_text(values.get("MEMWING_OPENCLAW_TIMEOUT_SECONDS"))
                or "60",
                name="MEMWING_MODEL_TIMEOUT_SECONDS",
            ),
        )

    @classmethod
    def from_plugin_config(
        cls,
        config: Mapping[str, object],
    ) -> MemWingModelConfigResolver:
        runtime = _runtime(_optional_text(config.get("modelRuntime")) or "openclaw")
        models = config.get("models")
        if models is None:
            role_models: dict[MemWingModelRole, str] = {}
        elif isinstance(models, Mapping):
            role_models = _role_models_from_plugin(models)
        else:
            raise ValueError("models must be an object when provided")

        return cls(
            runtime=runtime,
            role_models=role_models,
            default_model=None,
            transport="local" if runtime == "openclaw" else None,
            timeout_seconds=_positive_float(
                config.get("modelTimeoutSeconds", 60),
                name="modelTimeoutSeconds",
            ),
        )

    def selection_for(self, role: MemWingModelRole) -> MemWingModelSelection:
        if role not in MEMWING_MODEL_ROLES:
            raise ValueError(f"Unknown MemWing model role: {role}")
        model = self.role_models.get(role) or self.default_model
        if self.runtime == "openai_compatible" and model is None:
            raise ValueError(f"{role} requires a model for openai_compatible runtime")
        return MemWingModelSelection(
            role=role,
            runtime=self.runtime,
            model=model,
            transport=self.transport if self.runtime == "openclaw" else None,
            timeout_seconds=self.timeout_seconds,
        )


def _role_models_from_plugin(models: Mapping[object, object]) -> dict[MemWingModelRole, str]:
    role_models: dict[MemWingModelRole, str] = {}
    for key, value in models.items():
        if not isinstance(key, str) or key not in _PLUGIN_MODEL_KEYS:
            raise ValueError(f"Unknown MemWing model key: {key}")
        model = _optional_text(value)
        if model is not None:
            role_models[_PLUGIN_MODEL_KEYS[key]] = model
    return role_models


def _default_model(
    values: Mapping[str, str],
    runtime: MemWingModelRuntime,
) -> str | None:
    if runtime == "openclaw":
        return _optional_text(values.get("MEMWING_OPENCLAW_MODEL"))
    if runtime == "openai_compatible":
        return _optional_text(values.get("MEMWING_LLM_MODEL"))
    return None


def _runtime(value: str) -> MemWingModelRuntime:
    normalized = value.strip().lower()
    if normalized in {"test", "openai_compatible", "openclaw"}:
        return normalized
    raise ValueError("MemWing model runtime must be test, openai_compatible, or openclaw")


def _transport(value: str | None) -> MemWingModelTransport | None:
    if value is None:
        return "local"
    normalized = value.strip().lower()
    if normalized in {"local", "gateway"}:
        return normalized
    raise ValueError("MemWing model transport must be local or gateway")


def _positive_float(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive number")
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        number = float(value)
    else:
        raise ValueError(f"{name} must be a positive number")
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
