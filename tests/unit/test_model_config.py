from __future__ import annotations

import pytest

from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver


def test_model_config_resolver_uses_role_specific_env_over_runtime_default() -> None:
    resolver = MemWingModelConfigResolver.from_env(
        {
            "MEMWING_MODEL_RUNTIME": "openclaw",
            "MEMWING_OPENCLAW_MODEL": "current",
            "MEMWING_MODEL_PAGE_MEMORY": "page-model",
            "MEMWING_MODEL_TRANSPORT": "gateway",
            "MEMWING_MODEL_TIMEOUT_SECONDS": "45",
        }
    )

    page_memory = resolver.selection_for("page_memory")
    graphiti = resolver.selection_for("graphiti_extraction")

    assert page_memory.model == "page-model"
    assert page_memory.runtime == "openclaw"
    assert page_memory.transport == "gateway"
    assert page_memory.timeout_seconds == 45
    assert graphiti.model == "current"


def test_model_config_resolver_allows_openclaw_current_model() -> None:
    resolver = MemWingModelConfigResolver.from_env(
        {
            "MEMWING_MODEL_RUNTIME": "openclaw",
            "MEMWING_MODEL_TIMEOUT_SECONDS": "60",
        }
    )

    selection = resolver.selection_for("graphiti_extraction")

    assert selection.runtime == "openclaw"
    assert selection.model is None
    assert selection.transport == "local"


def test_model_config_resolver_rejects_missing_openai_compatible_model() -> None:
    resolver = MemWingModelConfigResolver.from_env(
        {
            "MEMWING_MODEL_RUNTIME": "openai_compatible",
            "MEMWING_MODEL_TIMEOUT_SECONDS": "60",
        }
    )

    with pytest.raises(ValueError, match="requires a model"):
        resolver.selection_for("long_term_filter")


def test_model_config_resolver_reads_openclaw_plugin_config_shape() -> None:
    resolver = MemWingModelConfigResolver.from_plugin_config(
        {
            "modelRuntime": "openclaw",
            "models": {
                "pageMemory": "page-current",
                "longTermFilter": "filter-current",
                "graphitiExtraction": "graph-current",
                "graphitiEmbedding": "embedding-current",
                "graphitiRerank": "rerank-current",
            },
            "modelTimeoutSeconds": 30,
        }
    )

    assert resolver.selection_for("page_memory").model == "page-current"
    assert resolver.selection_for("long_term_filter").model == "filter-current"
    assert resolver.selection_for("graphiti_extraction").model == "graph-current"
    assert resolver.selection_for("graphiti_embedding").model == "embedding-current"
    assert resolver.selection_for("graphiti_rerank").model == "rerank-current"
    assert resolver.selection_for("graphiti_rerank").timeout_seconds == 30


def test_model_config_resolver_rejects_unknown_plugin_model_key() -> None:
    with pytest.raises(ValueError, match="Unknown MemWing model key"):
        MemWingModelConfigResolver.from_plugin_config(
            {
                "modelRuntime": "openclaw",
                "models": {"graphitiExtractor": "bad-key"},
            }
        )
