from __future__ import annotations

from typing import get_args

from memwing.ports.model_runtime import (
    MEMWING_MODEL_ROLES,
    EmbeddingModelClient,
    LLMModelClient,
    LLMModelRequest,
    LLMModelResponse,
    MemWingModelRole,
    ModelCacheContext,
    MemWingModelSelection,
)


def test_model_runtime_roles_cover_product_model_paths() -> None:
    assert MEMWING_MODEL_ROLES == (
        "page_memory",
        "long_term_filter",
        "graphiti_extraction",
        "graphiti_embedding",
        "graphiti_rerank",
        "evidence_embedding",
    )
    assert set(get_args(MemWingModelRole)) == set(MEMWING_MODEL_ROLES)


def test_model_runtime_contract_keeps_text_and_embedding_clients_separate() -> None:
    assert hasattr(LLMModelClient, "complete")
    assert hasattr(EmbeddingModelClient, "embed")
    assert hasattr(EmbeddingModelClient, "embed_batch")


def test_model_selection_contract_is_role_scoped() -> None:
    selection = MemWingModelSelection(
        role="graphiti_extraction",
        runtime="openclaw",
        model=None,
        transport="local",
        timeout_seconds=60.0,
    )

    assert selection.role == "graphiti_extraction"
    assert selection.runtime == "openclaw"
    assert selection.model is None


def test_existing_llm_model_request_response_use_runtime_contract() -> None:
    context = ModelCacheContext(
        project_memory_space_id="project_001",
        source_event_ids=("source_001",),
        role="long_term_filter",
        prompt_hash="prompt:v1",
        schema_hash="long_term_filter:v1",
        cache_policy="required",
    )
    request = LLMModelRequest(
        system_prompt="system",
        user_prompt="user",
        trace_id="trace",
        cache_context=context,
    )
    response = LLMModelResponse(text="{}", provider="test", model="fake")

    assert request.system_prompt == "system"
    assert request.cache_context is context
    assert response.provider == "test"
