from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
import uuid

from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.model_result_cache import ModelResultCacheEntry, ModelResultCacheKey
from memwing.ports.model_runtime import (
    EmbeddingModelClient,
    MemWingModelRuntime,
    MemWingModelTransport,
    ModelCacheContext,
)


@dataclass(slots=True)
class ModelCacheMetrics:
    hits: int = 0
    misses: int = 0
    puts: int = 0
    invalidations: int = 0
    bypasses: int = 0
    provider_calls: int = 0


@dataclass(slots=True)
class _EmbeddingCacheMiss:
    text: str
    context: ModelCacheContext
    indexes: list[int]
    source_event_ids: tuple[str, ...]


class CachingEmbeddingModelClient(EmbeddingModelClient):
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        provider: EmbeddingModelClient,
        *,
        runtime: MemWingModelRuntime,
        model: str,
        transport: MemWingModelTransport,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider
        self._runtime = runtime
        self._model = model
        self._transport = transport
        self._now = now or (lambda: datetime.now(UTC))
        self.metrics = ModelCacheMetrics()

    async def embed(
        self,
        input: str,
        *,
        cache_context: ModelCacheContext | None = None,
    ) -> tuple[float, ...]:
        return (await self.embed_batch((input,), cache_contexts=(cache_context,)))[0]

    async def embed_batch(
        self,
        inputs: tuple[str, ...],
        *,
        cache_contexts: tuple[ModelCacheContext | None, ...] | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        if not inputs:
            return ()
        contexts = cache_contexts or tuple(None for _ in inputs)
        if len(contexts) != len(inputs):
            raise ValueError("embedding cache context count must match input count")

        now = self._now()
        results: list[tuple[float, ...] | None] = [None] * len(inputs)
        misses: dict[ModelResultCacheKey, _EmbeddingCacheMiss] = {}
        bypass_inputs: list[str] = []
        bypass_indexes: list[int] = []

        for index, (text, context) in enumerate(zip(inputs, contexts, strict=True)):
            if context is None or context.cache_policy == "bypass":
                self.metrics.bypasses += 1
                bypass_inputs.append(text)
                bypass_indexes.append(index)
                continue

            key = self._key(text, context)
            async with self._unit_of_work.transaction() as tx:
                hit = await tx.model_result_cache.get(key=key, now=now)
            if hit is not None and hit.embedding_vector is not None:
                merged_source_event_ids = _merge_source_event_ids(
                    hit.source_event_ids,
                    context.source_event_ids,
                )
                if merged_source_event_ids != hit.source_event_ids:
                    async with self._unit_of_work.transaction() as tx:
                        await tx.model_result_cache.put(
                            replace(hit, source_event_ids=merged_source_event_ids)
                        )
                self.metrics.hits += 1
                results[index] = hit.embedding_vector
                continue

            if key in misses:
                misses[key].indexes.append(index)
                misses[key].source_event_ids = _merge_source_event_ids(
                    misses[key].source_event_ids,
                    context.source_event_ids,
                )
            else:
                misses[key] = _EmbeddingCacheMiss(
                    text=text,
                    context=context,
                    indexes=[index],
                    source_event_ids=context.source_event_ids,
                )

        if misses:
            miss_items = tuple(misses.values())
            provider_inputs = tuple(miss.text for miss in miss_items)
            provider_vectors = await self._provider.embed_batch(provider_inputs)
            self.metrics.provider_calls += 1
            if len(provider_vectors) != len(provider_inputs):
                raise ValueError("embedding provider result count does not match input count")
            for miss, vector in zip(miss_items, provider_vectors, strict=True):
                self.metrics.misses += 1
                normalized_vector = tuple(float(value) for value in vector)
                entry = ModelResultCacheEntry(
                    id=str(uuid.uuid4()),
                    key=self._key(miss.text, miss.context),
                    source_event_ids=miss.source_event_ids,
                    value_json={"vector_size": len(normalized_vector)},
                    embedding_vector=normalized_vector,
                    status="active",
                    created_at=now,
                    last_hit_at=None,
                    hit_count=0,
                    invalidated_at=None,
                    invalidated_reason=None,
                    expires_at=None,
                )
                async with self._unit_of_work.transaction() as tx:
                    await tx.model_result_cache.put(entry)
                self.metrics.puts += 1
                for index in miss.indexes:
                    results[index] = normalized_vector

        if bypass_inputs:
            bypass_vectors = await self._provider.embed_batch(tuple(bypass_inputs))
            self.metrics.provider_calls += 1
            if len(bypass_vectors) != len(bypass_inputs):
                raise ValueError("embedding provider result count does not match input count")
            for index, vector in zip(bypass_indexes, bypass_vectors, strict=True):
                results[index] = tuple(float(value) for value in vector)

        return tuple(_required_vector(vector) for vector in results)

    def _key(self, text: str, context: ModelCacheContext) -> ModelResultCacheKey:
        return ModelResultCacheKey(
            project_memory_space_id=context.project_memory_space_id,
            cache_kind="embedding",
            role=context.role,
            runtime=self._runtime,
            model=self._model,
            transport=self._transport,
            prompt_hash=context.prompt_hash,
            input_hash=_hash_text(text),
            schema_hash=context.schema_hash,
        )


def _hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _required_vector(vector: tuple[float, ...] | None) -> tuple[float, ...]:
    if vector is None:
        raise RuntimeError("embedding cache failed to populate a vector")
    return vector


def _merge_source_event_ids(
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(sorted({*first, *second}))
