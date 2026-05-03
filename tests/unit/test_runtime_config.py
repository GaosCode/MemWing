import pytest

from memwing.api.env import load_app_env
from memwing.api.runtime_config import (
    OpenClawRuntimeUnavailableError,
    benchmark_admin_enabled_from_env,
    database_url_from_env,
    evidence_backend_from_env,
    evidence_vector_size_from_env,
    graph_backend_from_env,
    graphiti_neo4j_password_from_env,
    qdrant_collection_from_env,
    qdrant_url_from_env,
)


def test_runtime_config_reads_graph_and_evidence_defaults() -> None:
    assert graph_backend_from_env({}) == "disabled"
    assert evidence_backend_from_env({}) == "disabled"
    assert qdrant_url_from_env({}) == "http://127.0.0.1:6333"
    assert qdrant_collection_from_env({}) == "memwing_evidence"
    assert evidence_vector_size_from_env({}) == 1536
    assert graphiti_neo4j_password_from_env({"MEMWING_GRAPHITI_NEO4J_PASSWORD": "   "}) is None


def test_runtime_config_reads_qdrant_env_values() -> None:
    env = {
        "MEMWING_EVIDENCE_BACKEND": " qdrant ",
        "QDRANT_URL": " http://qdrant.local:6333 ",
        "QDRANT_COLLECTION": " evidence_test ",
        "MEMWING_EVIDENCE_VECTOR_SIZE": " 768 ",
    }

    assert evidence_backend_from_env(env) == "qdrant"
    assert qdrant_url_from_env(env) == "http://qdrant.local:6333"
    assert qdrant_collection_from_env(env) == "evidence_test"
    assert evidence_vector_size_from_env(env) == 768


def test_runtime_config_rejects_invalid_backends() -> None:
    with pytest.raises(OpenClawRuntimeUnavailableError, match="MEMWING_GRAPH_BACKEND"):
        graph_backend_from_env({"MEMWING_GRAPH_BACKEND": "neo4j"})

    with pytest.raises(OpenClawRuntimeUnavailableError, match="MEMWING_EVIDENCE_BACKEND"):
        evidence_backend_from_env({"MEMWING_EVIDENCE_BACKEND": "postgres"})


@pytest.mark.parametrize("raw_value", ["0", "-1", "bad"])
def test_runtime_config_rejects_invalid_evidence_vector_size(raw_value: str) -> None:
    with pytest.raises(OpenClawRuntimeUnavailableError, match="MEMWING_EVIDENCE_VECTOR_SIZE"):
        evidence_vector_size_from_env({"MEMWING_EVIDENCE_VECTOR_SIZE": raw_value})


def test_benchmark_admin_enabled_requires_literal_true() -> None:
    assert benchmark_admin_enabled_from_env({"MEMWING_BENCHMARK_ADMIN_ENABLED": "true"}) is True
    assert benchmark_admin_enabled_from_env({"MEMWING_BENCHMARK_ADMIN_ENABLED": "1"}) is False
    assert benchmark_admin_enabled_from_env({}) is False


def test_load_app_env_reads_dotenv_from_current_working_tree(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=postgresql://memwing@localhost/memwing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    load_app_env()

    assert database_url_from_env() == "postgresql://memwing@localhost/memwing"
