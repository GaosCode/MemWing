from __future__ import annotations

from collections.abc import Iterable

from graphiti_core.embedder import EmbedderClient

from memwing.infrastructure.graph.graphiti_cache_context import graphiti_embedding_cache_context
from memwing.ports.model_runtime import EmbeddingModelClient


class GraphitiMemWingEmbedder(EmbedderClient):
    def __init__(self, client: EmbeddingModelClient) -> None:
        self._client = client
        self.cache_metrics = getattr(client, "metrics", None)

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> list[float]:
        if isinstance(input_data, list) and len(input_data) == 1 and isinstance(input_data[0], str):
            input_data = input_data[0]
        if not isinstance(input_data, str):
            raise ValueError("Graphiti MemWing embedder requires text input")
        cache_context = graphiti_embedding_cache_context()
        if cache_context is None:
            embedding = await self._client.embed(input_data)
        else:
            embedding = await self._client.embed(input_data, cache_context=cache_context)
        return [float(value) for value in embedding]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        cache_context = graphiti_embedding_cache_context()
        if cache_context is None:
            embeddings = await self._client.embed_batch(tuple(input_data_list))
        else:
            embeddings = await self._client.embed_batch(
                tuple(input_data_list),
                cache_contexts=tuple(cache_context for _ in input_data_list),
            )
        return [[float(value) for value in embedding] for embedding in embeddings]
