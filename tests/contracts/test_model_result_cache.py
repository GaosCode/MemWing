import asyncio
from datetime import UTC, datetime

from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.model_result_cache import (
    ModelResultCacheEntry,
    ModelResultCacheKey,
)


NOW = datetime(2026, 5, 5, tzinfo=UTC)


def test_model_result_cache_is_project_scoped_and_lineage_queryable() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        key = ModelResultCacheKey(
            project_memory_space_id="project_001",
            cache_kind="embedding",
            role="evidence_embedding",
            runtime="openclaw",
            model="embedding-model",
            transport="local",
            prompt_hash="none",
            input_hash="input_hash",
            schema_hash="embedding:v1",
        )
        entry = ModelResultCacheEntry(
            id="cache_001",
            key=key,
            source_event_ids=("source_001",),
            value_json={"vector_size": 2},
            embedding_vector=(0.1, 0.2),
            status="active",
            created_at=NOW,
            last_hit_at=None,
            hit_count=0,
            invalidated_at=None,
            invalidated_reason=None,
            expires_at=None,
        )

        async with store.transaction() as tx:
            await tx.model_result_cache.put(entry)
            hit = await tx.model_result_cache.get(key=key, now=NOW)
            cross_project = await tx.model_result_cache.get(
                key=ModelResultCacheKey(
                    project_memory_space_id="project_002",
                    cache_kind=key.cache_kind,
                    role=key.role,
                    runtime=key.runtime,
                    model=key.model,
                    transport=key.transport,
                    prompt_hash=key.prompt_hash,
                    input_hash=key.input_hash,
                    schema_hash=key.schema_hash,
                ),
                now=NOW,
            )
            by_source = await tx.model_result_cache.list_by_source_event(
                project_memory_space_id="project_001",
                source_event_id="source_001",
            )

        assert hit is not None
        assert hit.id == "cache_001"
        assert hit.hit_count == 1
        assert cross_project is None
        assert tuple(item.id for item in by_source) == ("cache_001",)

    asyncio.run(scenario())


def test_model_result_cache_put_merges_source_lineage_for_existing_key() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        first = _entry(
            cache_id="cache_001",
            source_event_ids=("source_001",),
        )
        second = _entry(
            cache_id="cache_002",
            source_event_ids=("source_002", "source_001"),
        )

        async with store.transaction() as tx:
            await tx.model_result_cache.put(first)
            merged = await tx.model_result_cache.put(second)
            by_first_source = await tx.model_result_cache.list_by_source_event(
                project_memory_space_id="project_001",
                source_event_id="source_001",
            )
            by_second_source = await tx.model_result_cache.list_by_source_event(
                project_memory_space_id="project_001",
                source_event_id="source_002",
            )

        assert merged.id == "cache_001"
        assert merged.source_event_ids == ("source_001", "source_002")
        assert tuple(item.id for item in by_first_source) == ("cache_001",)
        assert tuple(item.id for item in by_second_source) == ("cache_001",)

    asyncio.run(scenario())


def _entry(
    *,
    cache_id: str,
    source_event_ids: tuple[str, ...],
) -> ModelResultCacheEntry:
    return ModelResultCacheEntry(
        id=cache_id,
        key=ModelResultCacheKey(
            project_memory_space_id="project_001",
            cache_kind="embedding",
            role="evidence_embedding",
            runtime="openclaw",
            model="embedding-model",
            transport="local",
            prompt_hash="none",
            input_hash="input_hash",
            schema_hash="embedding:v1",
        ),
        source_event_ids=source_event_ids,
        value_json={"vector_size": 2},
        embedding_vector=(0.1, 0.2),
        status="active",
        created_at=NOW,
        last_hit_at=None,
        hit_count=0,
        invalidated_at=None,
        invalidated_reason=None,
        expires_at=None,
    )
