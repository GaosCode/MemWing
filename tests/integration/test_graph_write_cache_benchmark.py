import asyncio
from dataclasses import replace
from statistics import quantiles
from time import perf_counter

from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.llm.caching_embedding import CachingEmbeddingModelClient
from memwing.ports.graph_backend import GraphWriteBatchItemResult, GraphWriteBatchResult
from memwing.ports.model_runtime import ModelCacheContext
from memwing.workers.graph_write_worker import GraphWriteWorker
from tests.integration.graph_write_worker_fixtures import (
    NOW,
    graph_job,
    memory_item,
    source_event,
    successful_graph_result,
)


def test_graph_write_cache_benchmark_evidence_records_core_metrics() -> None:
    evidence = asyncio.run(_run_graph_write_cache_benchmark(job_count=20))

    assert evidence["graph_write_jobs"] == 40
    assert evidence["graph_write_qps"] > 0
    assert evidence["graph_write_p95_latency_ms"] >= 0
    assert evidence["cache_hit_rate"] == 0.5
    assert evidence["cache_hits"] == 20
    assert evidence["cache_misses"] == 20
    assert evidence["provider_batch_calls"] == 2
    assert evidence["provider_vector_count"] == 20


async def _run_graph_write_cache_benchmark(*, job_count: int) -> dict[str, float | int]:
    store = InMemoryDataStore()
    provider = CountingEmbeddingProvider()
    embedding_client = CachingEmbeddingModelClient(
        store,
        provider,
        runtime="test",
        model="benchmark-embedding",
        transport="local",
        now=lambda: NOW,
    )
    backend = EmbeddingGraphBackend(embedding_client)
    worker = GraphWriteWorker(
        store,
        graph_backend=backend,
        worker_id="benchmark_worker",
        batch_size=10,
    )
    await _seed_memory_inputs(store, job_count=job_count)

    latencies: list[float] = []
    total_claimed = 0
    started = perf_counter()
    for phase in ("initial", "retry"):
        await _enqueue_graph_jobs(store, job_count=job_count, phase=phase)
        while True:
            before = perf_counter()
            result = await worker.run_once(now=NOW)
            elapsed = perf_counter() - before
            if result.claimed == 0:
                break
            latencies.append(elapsed)
            total_claimed += result.claimed

    total_elapsed = perf_counter() - started
    metrics = embedding_client.metrics
    cache_hit_rate = metrics.hits / (metrics.hits + metrics.misses)
    p95_latency = quantiles(latencies, n=20)[18] if len(latencies) >= 2 else latencies[0]
    return {
        "graph_write_jobs": total_claimed,
        "graph_write_qps": total_claimed / total_elapsed,
        "graph_write_p95_latency_ms": p95_latency * 1000,
        "cache_hit_rate": cache_hit_rate,
        "cache_hits": metrics.hits,
        "cache_misses": metrics.misses,
        "provider_batch_calls": provider.batch_calls,
        "provider_vector_count": provider.vector_count,
    }


async def _seed_memory_inputs(store: InMemoryDataStore, *, job_count: int) -> None:
    async with store.transaction() as tx:
        for index in range(job_count):
            source = replace(
                source_event(),
                id=f"source_{index:03d}",
                content=f"Decision source text {index}",
                content_preview=f"Decision source text {index}",
                raw_payload_hash=f"hash_{index:03d}",
                runtime_event_idempotency_key=f"runtime-key-{index:03d}",
            )
            memory = replace(
                memory_item(),
                id=f"memory_{index:03d}",
                content=f"Decision text {index}",
                source_event_ids=(source.id,),
                primary_source_event_id=source.id,
            )
            await tx.source_events.insert_if_absent(source)
            await tx.memory_items.upsert(memory)


async def _enqueue_graph_jobs(
    store: InMemoryDataStore,
    *,
    job_count: int,
    phase: str,
) -> None:
    async with store.transaction() as tx:
        for index in range(job_count):
            await tx.graph_write_jobs.enqueue(
                replace(
                    graph_job(),
                    id=f"graph_job_{phase}_{index:03d}",
                    memory_id=f"memory_{index:03d}",
                    source_event_ids=(f"source_{index:03d}",),
                    idempotency_key=f"graph:{phase}:{index:03d}",
                    next_run_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


class CountingEmbeddingProvider:
    def __init__(self) -> None:
        self.batch_calls = 0
        self.vector_count = 0

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
        self.batch_calls += 1
        self.vector_count += len(inputs)
        return tuple((float(len(text)),) for text in inputs)


class EmbeddingGraphBackend:
    def __init__(self, embedding_client: CachingEmbeddingModelClient) -> None:
        self._embedding_client = embedding_client

    async def ingest_graph_job(self, request):
        result = await self.ingest_graph_jobs(type("Batch", (), {"requests": (request,)})())
        return result.items[0].result

    async def ingest_graph_jobs(self, request) -> GraphWriteBatchResult:
        await self._embedding_client.embed_batch(
            tuple(item.memory_item.content for item in request.requests),
            cache_contexts=tuple(_cache_context_for(item) for item in request.requests),
        )
        graph_result = successful_graph_result()
        return GraphWriteBatchResult(
            items=tuple(
                GraphWriteBatchItemResult(
                    job_id=item.job.id,
                    result=graph_result,
                    error_type=None,
                    error_message=None,
                    reason_code=None,
                    retryable=False,
                )
                for item in request.requests
            )
        )

    def cache_metrics_snapshot(self) -> dict[str, int]:
        metrics = self._embedding_client.metrics
        return {
            "embedding_hits": metrics.hits,
            "embedding_misses": metrics.misses,
            "embedding_provider_calls": metrics.provider_calls,
        }


def _cache_context_for(item) -> ModelCacheContext:
    return ModelCacheContext(
        project_memory_space_id=item.job.project_memory_space_id,
        source_event_ids=item.job.source_event_ids,
        role="graphiti_embedding",
        prompt_hash="none",
        schema_hash="graphiti_embedding:v1",
    )
