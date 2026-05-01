from __future__ import annotations

import asyncio

import pytest
from graphiti_core.embedder import EmbedderClient

from memwing.infrastructure.graph.graphiti_embedder import GraphitiMemWingEmbedder
from memwing.infrastructure.llm.errors import LLMProviderError


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.single_inputs: list[str] = []
        self.batch_inputs: list[tuple[str, ...]] = []

    async def embed(self, input: str) -> tuple[float, ...]:
        self.single_inputs.append(input)
        return (1.0, 2.0, 3.0)

    async def embed_batch(self, inputs: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.batch_inputs.append(inputs)
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


def test_graphiti_embedder_rejects_non_text_single_input() -> None:
    embedder = GraphitiMemWingEmbedder(FakeEmbeddingClient())

    async def scenario() -> None:
        await embedder.create([1, 2, 3])

    with pytest.raises(ValueError, match="requires text input"):
        asyncio.run(scenario())


def test_graphiti_embedder_surfaces_provider_failure() -> None:
    class FailingEmbeddingClient(FakeEmbeddingClient):
        async def embed(self, input: str) -> tuple[float, ...]:
            raise LLMProviderError("embedding provider failed")

    embedder = GraphitiMemWingEmbedder(FailingEmbeddingClient())

    async def scenario() -> None:
        await embedder.create("graph fact")

    with pytest.raises(LLMProviderError, match="embedding provider failed"):
        asyncio.run(scenario())
