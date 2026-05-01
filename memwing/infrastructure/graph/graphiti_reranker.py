from __future__ import annotations


class GraphitiNoProviderReranker:
    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(passage, 0.0) for passage in passages]
