from __future__ import annotations

from memwing.config_store import default_config
from memwing.profiles import apply_profile_template, build_profile_config
from memwing.runtime_env import build_runtime_env


def test_full_local_profile_defaults_to_local_services_and_openclaw_runtime() -> None:
    config = build_profile_config("full-local")
    env = build_runtime_env(config, base_env={}).env

    assert config["profile"] == "full-local"
    assert env["MEMWING_MODEL_RUNTIME"] == "openclaw"
    assert env["MEMWING_STORAGE_BACKEND"] == "postgres"
    assert env["DATABASE_URL"].startswith("postgresql://")
    assert env["MEMWING_GRAPH_BACKEND"] == "graphiti"
    assert env["MEMWING_GRAPHITI_NEO4J_URI"] == "bolt://127.0.0.1:7687"
    assert env["MEMWING_EVIDENCE_BACKEND"] == "qdrant"
    assert env["MEMWING_QDRANT_URL"] == "http://127.0.0.1:6333"


def test_production_profile_renders_external_infra_config_without_local_defaults() -> None:
    config = build_profile_config("production")
    env = build_runtime_env(config, base_env={}).env

    assert config["profile"] == "production"
    assert env["MEMWING_MODEL_RUNTIME"] == "openclaw"
    assert env["MEMWING_STORAGE_BACKEND"] == "postgres"
    assert "DATABASE_URL" not in env
    assert env["MEMWING_GRAPH_BACKEND"] == "graphiti"
    assert "MEMWING_GRAPHITI_NEO4J_URI" not in env
    assert env["MEMWING_EVIDENCE_BACKEND"] == "qdrant"
    assert "MEMWING_QDRANT_URL" not in env


def test_profile_template_preserves_explicit_model_runtime_override() -> None:
    config = default_config()
    config["runtime"]["modelRuntime"] = "custom-runtime"

    apply_profile_template(config, "production")

    assert config["runtime"]["modelRuntime"] == "custom-runtime"
    assert config["profile"] == "production"
