from __future__ import annotations

import asyncio

import pytest
from graphiti_core.embedder import EmbedderClient

from memwing.infrastructure.graph.graphiti_cache_context import graphiti_model_cache_context
from memwing.infrastructure.graph.graphiti_embedder import GraphitiMemWingEmbedder
from memwing.infrastructure.llm.errors import LLMProviderError
from memwing.ports.model_runtime import ModelCacheContext


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.single_inputs: list[str] = []
        self.batch_inputs: list[tuple[str, ...]] = []
        self.single_contexts: list[ModelCacheContext | None] = []
        self.batch_contexts: list[tuple[ModelCacheContext | None, ...] | None] = []

    async def embed(
        self,
        input: str,
        *,
        cache_context: ModelCacheContext | None = None,
    ) -> tuple[float, ...]:
        self.single_inputs.append(input)
        self.single_contexts.append(cache_context)
        return (1.0, 2.0, 3.0)

    async def embed_batch(
        self,
        inputs: tuple[str, ...],
        *,
        cache_contexts: tuple[ModelCacheContext | None, ...] | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        self.batch_inputs.append(inputs)
        self.batch_contexts.append(cache_contexts)
        return tuple((float(index), float(index + 1)) for index, _ in enumerate(inputs))


def test_graphiti_embedder_create_uses_memwing_embedding_client() -> None:
    fake = FakeEmbeddingClient()
    embedder = GraphitiMemWingEmbedder(fake)

    async def scenario() -> list[float]:
        return await embedder.create("graph fact")

    assert asyncio.run(scenario()) == [1.0, 2.0, 3.0]
    assert fake.single_inputs == ["graph fact"]
    assert isinstance(embedder, EmbedderClient)


def test_graphiti_embedder_create_accepts_graphiti_single_text_list() -> None:
    fake = FakeEmbeddingClient()
    embedder = GraphitiMemWingEmbedder(fake)

    async def scenario() -> list[float]:
        return await embedder.create(["graph fact"])

    assert asyncio.run(scenario()) == [1.0, 2.0, 3.0]
    assert fake.single_inputs == ["graph fact"]


def test_graphiti_embedder_create_batch_preserves_order() -> None:
    fake = FakeEmbeddingClient()
    embedder = GraphitiMemWingEmbedder(fake)

    async def scenario() -> list[list[float]]:
        return await embedder.create_batch(["first", "second", "third"])

    assert asyncio.run(scenario()) == [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]]
    assert fake.batch_inputs == [("first", "second", "third")]


def test_graphiti_embedder_passes_graph_write_cache_context() -> None:
    fake = FakeEmbeddingClient()
    embedder = GraphitiMemWingEmbedder(fake)

    async def scenario() -> list[list[float]]:
        with graphiti_model_cache_context(
            project_memory_space_id="project_001",
            source_event_ids=("source_001",),
        ):
            return await embedder.create_batch(["first", "second"])

    assert asyncio.run(scenario()) == [[0.0, 1.0], [1.0, 2.0]]
    assert fake.batch_contexts[0] is not None
    contexts = fake.batch_contexts[0] or ()
    assert tuple(context.role for context in contexts if context is not None) == (
        "graphiti_embedding",
        "graphiti_embedding",
    )
    assert contexts[0] is not None
    assert contexts[0].project_memory_space_id == "project_001"
    assert contexts[0].source_event_ids == ("source_001",)
    assert contexts[0].schema_hash == "graphiti_embedding:v1"


def test_graphiti_embedder_rejects_non_text_single_input() -> None:
    embedder = GraphitiMemWingEmbedder(FakeEmbeddingClient())

    async def scenario() -> None:
        await embedder.create([1, 2, 3])

    with pytest.raises(ValueError, match="requires text input"):
        asyncio.run(scenario())


def test_graphiti_embedder_surfaces_provider_failure() -> None:
    class FailingEmbeddingClient(FakeEmbeddingClient):
        async def embed(
            self,
            input: str,
            *,
            cache_context: ModelCacheContext | None = None,
        ) -> tuple[float, ...]:
            raise LLMProviderError("embedding provider failed")

    embedder = GraphitiMemWingEmbedder(FailingEmbeddingClient())

    async def scenario() -> None:
        await embedder.create("graph fact")

    with pytest.raises(LLMProviderError, match="embedding provider failed"):
        asyncio.run(scenario())
