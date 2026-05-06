from __future__ import annotations

from memwing.config_store import default_config, set_config_value
from memwing.runtime_env import build_runtime_env


def test_build_runtime_env_maps_config_to_child_process_env() -> None:
    config = default_config()
    set_config_value(config, "database.url", "postgresql://memwing@localhost/memwing")
    set_config_value(config, "profile", "production")
    set_config_value(config, "api.port", 9000)
    set_config_value(config, "graph.backend", "graphiti")
    set_config_value(config, "evidence.backend", "qdrant")
    set_config_value(config, "evidence.qdrant.url", "http://qdrant.local:6333")

    runtime_env = build_runtime_env(config, base_env={})

    assert runtime_env.profile == "production"
    assert runtime_env.env["MEMWING_PROFILE"] == "production"
    assert runtime_env.env["MEMWING_API_PORT"] == "9000"
    assert runtime_env.env["DATABASE_URL"] == "postgresql://memwing@localhost/memwing"
    assert runtime_env.env["MEMWING_GRAPH_BACKEND"] == "graphiti"
    assert runtime_env.env["MEMWING_EVIDENCE_BACKEND"] == "qdrant"
    assert runtime_env.env["QDRANT_URL"] == "http://qdrant.local:6333"


def test_runtime_env_redacts_secret_values_by_name() -> None:
    config = default_config()
    set_config_value(config, "graph.neo4j.password", "neo4j-password")
    set_config_value(config, "evidence.qdrant.apiKey", "qdrant-key")

    redacted = build_runtime_env(config, base_env={}).redacted()

    assert redacted["MEMWING_GRAPHITI_NEO4J_PASSWORD"] == "<redacted>"
    assert redacted["MEMWING_QDRANT_API_KEY"] == "<redacted>"
