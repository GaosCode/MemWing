from __future__ import annotations

from collections.abc import Iterable

from graphiti_core.embedder import EmbedderClient

from memwing.ports.model_runtime import EmbeddingModelClient


class GraphitiMemWingEmbedder(EmbedderClient):
    def __init__(self, client: EmbeddingModelClient) -> None:
        self._client = client

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> list[float]:
        if isinstance(input_data, list) and len(input_data) == 1 and isinstance(input_data[0], str):
            input_data = input_data[0]
        if not isinstance(input_data, str):
            raise ValueError("Graphiti MemWing embedder requires text input")
        embedding = await self._client.embed(input_data)
        return [float(value) for value in embedding]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        embeddings = await self._client.embed_batch(tuple(input_data_list))
        return [[float(value) for value in embedding] for embedding in embeddings]
