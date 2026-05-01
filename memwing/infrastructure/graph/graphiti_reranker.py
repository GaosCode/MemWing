from __future__ import annotations

from graphiti_core.cross_encoder import CrossEncoderClient


class GraphitiNoProviderReranker(CrossEncoderClient):
    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(passage, 0.0) for passage in passages]
