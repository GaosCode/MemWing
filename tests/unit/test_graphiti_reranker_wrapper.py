from __future__ import annotations

import asyncio

from memwing.infrastructure.graph.graphiti_reranker import GraphitiNoProviderReranker


def test_no_provider_reranker_returns_passages_in_input_order() -> None:
    reranker = GraphitiNoProviderReranker()

    async def scenario() -> list[tuple[str, float]]:
        return await reranker.rank("roadmap", ["first", "second", "third"])

    assert asyncio.run(scenario()) == [
        ("first", 0.0),
        ("second", 0.0),
        ("third", 0.0),
    ]


def test_no_provider_reranker_handles_empty_passages() -> None:
    reranker = GraphitiNoProviderReranker()

    async def scenario() -> list[tuple[str, float]]:
        return await reranker.rank("roadmap", [])

    assert asyncio.run(scenario()) == []
