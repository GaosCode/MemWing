import asyncio
from datetime import UTC, datetime

from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.llm.caching_embedding import CachingEmbeddingModelClient
from memwing.ports.model_runtime import ModelCacheContext


NOW = datetime(2026, 5, 5, tzinfo=UTC)


def test_caching_embedding_client_deduplicates_batch_misses_and_preserves_order() -> None:
    store = InMemoryDataStore()
    provider = FakeEmbeddingClient(
        {
            "alpha": (1.0, 0.0),
            "beta": (0.0, 1.0),
        }
    )
    client = CachingEmbeddingModelClient(
        store,
        provider,
        runtime="openclaw",
        model="embedding-model",
        transport="local",
        now=lambda: NOW,
    )

    async def scenario() -> None:
        contexts = (
            _context("source_001"),
            _context("source_001"),
            _context("source_002"),
        )
        first = await client.embed_batch(("alpha", "alpha", "beta"), cache_contexts=contexts)
        second = await client.embed_batch(("alpha", "beta"), cache_contexts=contexts[::2])
        bypass = await client.embed_batch(("alpha",), cache_contexts=(None,))

        assert first == ((1.0, 0.0), (1.0, 0.0), (0.0, 1.0))
        assert second == ((1.0, 0.0), (0.0, 1.0))
        assert bypass == ((1.0, 0.0),)

    asyncio.run(scenario())

    assert provider.batch_calls == (("alpha", "beta"), ("alpha",))
    assert client.metrics.misses == 2
    assert client.metrics.hits == 2
    assert client.metrics.bypasses == 1


def test_caching_embedding_client_merges_lineage_for_equal_inputs() -> None:
    store = InMemoryDataStore()
    provider = FakeEmbeddingClient({"alpha": (1.0, 0.0)})
    client = CachingEmbeddingModelClient(
        store,
        provider,
        runtime="openclaw",
        model="embedding-model",
        transport="local",
        now=lambda: NOW,
    )

    async def scenario() -> None:
        await client.embed_batch(
            ("alpha", "alpha"),
            cache_contexts=(_context("source_001"), _context("source_002")),
        )
        await client.embed_batch(("alpha",), cache_contexts=(_context("source_003"),))

        async with store.transaction() as tx:
            rows = []
            for source_event_id in ("source_001", "source_002", "source_003"):
                rows.append(
                    await tx.model_result_cache.list_by_source_event(
                        project_memory_space_id="project_001",
                        source_event_id=source_event_id,
                    )
                )

        assert tuple(tuple(row.source_event_ids for row in rows_for_source) for rows_for_source in rows) == (
            (("source_001", "source_002", "source_003"),),
            (("source_001", "source_002", "source_003"),),
            (("source_001", "source_002", "source_003"),),
        )

    asyncio.run(scenario())

    assert provider.batch_calls == (("alpha",),)
    assert client.metrics.misses == 1
    assert client.metrics.hits == 1


class FakeEmbeddingClient:
    def __init__(self, vectors: dict[str, tuple[float, ...]]) -> None:
        self._vectors = vectors
        self.batch_calls: tuple[tuple[str, ...], ...] = ()

    async def embed(self, input: str, *, cache_context=None) -> tuple[float, ...]:
        return (await self.embed_batch((input,), cache_contexts=(cache_context,)))[0]

    async def embed_batch(
        self,
        inputs: tuple[str, ...],
        *,
        cache_contexts=None,
    ) -> tuple[tuple[float, ...], ...]:
        self.batch_calls = (*self.batch_calls, inputs)
        return tuple(self._vectors[item] for item in inputs)


def _context(source_event_id: str) -> ModelCacheContext:
    return ModelCacheContext(
        project_memory_space_id="project_001",
        source_event_ids=(source_event_id,),
        role="evidence_embedding",
        prompt_hash="none",
        schema_hash="embedding:v1",
        cache_policy="required",
    )
