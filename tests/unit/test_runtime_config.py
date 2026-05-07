import pytest

from memwing.api.env import load_app_env
from memwing.api.runtime_config import (
    OpenClawRuntimeUnavailableError,
    auto_push_enabled_from_env,
    benchmark_admin_enabled_from_env,
    database_url_from_env,
    evidence_backend_from_env,
    evidence_vector_size_from_env,
    feishu_push_config_from_env,
    graph_backend_from_env,
    graph_write_batch_size_from_env,
    graph_write_max_global_concurrency_from_env,
    graph_write_max_project_concurrency_from_env,
    graph_write_timeout_seconds_from_env,
    graphiti_neo4j_password_from_env,
    graphiti_semantic_bulk_enabled_from_env,
    qdrant_collection_from_env,
    qdrant_url_from_env,
)


def test_runtime_config_reads_graph_and_evidence_defaults() -> None:
    assert graph_backend_from_env({}) == "disabled"
    assert evidence_backend_from_env({}) == "disabled"
    assert qdrant_url_from_env({}) == "http://127.0.0.1:6333"
    assert qdrant_collection_from_env({}) == "memwing_evidence"
    assert evidence_vector_size_from_env({}) == 1536
    assert graph_write_timeout_seconds_from_env({}) == 900
    assert graph_write_batch_size_from_env({}) == 1
    assert graph_write_max_project_concurrency_from_env({}) == 1
    assert graph_write_max_global_concurrency_from_env({}) == 16
    assert graphiti_semantic_bulk_enabled_from_env({}) is False
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


@pytest.mark.parametrize("raw_value", ["0", "-1", "bad"])
def test_runtime_config_rejects_invalid_graph_write_timeout(raw_value: str) -> None:
    with pytest.raises(OpenClawRuntimeUnavailableError, match="MEMWING_GRAPH_WRITE_TIMEOUT_SECONDS"):
        graph_write_timeout_seconds_from_env({"MEMWING_GRAPH_WRITE_TIMEOUT_SECONDS": raw_value})


def test_runtime_config_reads_graph_write_batching_env_values() -> None:
    env = {
        "MEMWING_GRAPH_WRITE_BATCH_SIZE": " 4 ",
        "MEMWING_GRAPH_WRITE_MAX_PROJECT_CONCURRENCY": " 2 ",
        "MEMWING_GRAPH_WRITE_MAX_GLOBAL_CONCURRENCY": " 9 ",
    }

    assert graph_write_batch_size_from_env(env) == 4
    assert graph_write_max_project_concurrency_from_env(env) == 2
    assert graph_write_max_global_concurrency_from_env(env) == 9


@pytest.mark.parametrize("name", [
    "MEMWING_GRAPH_WRITE_BATCH_SIZE",
    "MEMWING_GRAPH_WRITE_MAX_PROJECT_CONCURRENCY",
    "MEMWING_GRAPH_WRITE_MAX_GLOBAL_CONCURRENCY",
])
@pytest.mark.parametrize("raw_value", ["0", "-1", "bad"])
def test_runtime_config_rejects_invalid_graph_write_batching_values(
    name: str,
    raw_value: str,
) -> None:
    readers = {
        "MEMWING_GRAPH_WRITE_BATCH_SIZE": graph_write_batch_size_from_env,
        "MEMWING_GRAPH_WRITE_MAX_PROJECT_CONCURRENCY": (
            graph_write_max_project_concurrency_from_env
        ),
        "MEMWING_GRAPH_WRITE_MAX_GLOBAL_CONCURRENCY": graph_write_max_global_concurrency_from_env,
    }

    with pytest.raises(OpenClawRuntimeUnavailableError, match=name):
        readers[name]({name: raw_value})


def test_benchmark_admin_enabled_requires_literal_true() -> None:
    assert benchmark_admin_enabled_from_env({"MEMWING_BENCHMARK_ADMIN_ENABLED": "true"}) is True
    assert benchmark_admin_enabled_from_env({"MEMWING_BENCHMARK_ADMIN_ENABLED": "1"}) is False
    assert benchmark_admin_enabled_from_env({}) is False


def test_graphiti_semantic_bulk_requires_literal_true() -> None:
    assert graphiti_semantic_bulk_enabled_from_env(
        {"MEMWING_GRAPHITI_SEMANTIC_BULK_ENABLED": "true"}
    ) is True
    assert graphiti_semantic_bulk_enabled_from_env(
        {"MEMWING_GRAPHITI_SEMANTIC_BULK_ENABLED": "1"}
    ) is False
    assert graphiti_semantic_bulk_enabled_from_env({}) is False


def test_feishu_push_config_requires_explicit_enablement() -> None:
    assert feishu_push_config_from_env({}) is None
    assert feishu_push_config_from_env({"MEMWING_FEISHU_PUSH_ENABLED": "1"}) is None


def test_auto_push_requires_explicit_enablement() -> None:
    assert auto_push_enabled_from_env({}) is False
    assert auto_push_enabled_from_env({"MEMWING_AUTO_PUSH_ENABLED": "1"}) is False
    assert auto_push_enabled_from_env({"MEMWING_AUTO_PUSH_ENABLED": "true"}) is True


def test_feishu_push_config_reads_required_values() -> None:
    config = feishu_push_config_from_env(
        {
            "MEMWING_FEISHU_PUSH_ENABLED": "true",
            "MEMWING_FEISHU_APP_ID": " cli_001 ",
            "MEMWING_FEISHU_APP_SECRET": " secret ",
            "MEMWING_FEISHU_RECEIVE_ID_TYPE": " chat_id ",
            "MEMWING_FEISHU_API_BASE_URL": " https://open.feishu.cn/open-apis/ ",
            "MEMWING_FEISHU_TIMEOUT_SECONDS": " 5 ",
        }
    )

    assert config is not None
    assert config.app_id == "cli_001"
    assert config.app_secret == "secret"
    assert config.receive_id_type == "chat_id"
    assert config.api_base_url == "https://open.feishu.cn/open-apis/"
    assert config.timeout_seconds == 5


def test_feishu_push_config_rejects_missing_or_invalid_values() -> None:
    with pytest.raises(OpenClawRuntimeUnavailableError, match="MEMWING_FEISHU_APP_ID"):
        feishu_push_config_from_env({"MEMWING_FEISHU_PUSH_ENABLED": "true"})

    with pytest.raises(OpenClawRuntimeUnavailableError, match="MEMWING_FEISHU_RECEIVE_ID_TYPE"):
        feishu_push_config_from_env(
            {
                "MEMWING_FEISHU_PUSH_ENABLED": "true",
                "MEMWING_FEISHU_APP_ID": "cli_001",
                "MEMWING_FEISHU_APP_SECRET": "secret",
                "MEMWING_FEISHU_RECEIVE_ID_TYPE": "department_id",
            }
        )

    with pytest.raises(OpenClawRuntimeUnavailableError, match="MEMWING_FEISHU_TIMEOUT_SECONDS"):
        feishu_push_config_from_env(
            {
                "MEMWING_FEISHU_PUSH_ENABLED": "true",
                "MEMWING_FEISHU_APP_ID": "cli_001",
                "MEMWING_FEISHU_APP_SECRET": "secret",
                "MEMWING_FEISHU_TIMEOUT_SECONDS": "0",
            }
        )


def test_load_app_env_reads_dotenv_from_current_working_tree(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=postgresql://memwing@localhost/memwing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    load_app_env()

    assert database_url_from_env() == "postgresql://memwing@localhost/memwing"
