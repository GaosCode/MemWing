import asyncio
from dataclasses import replace
from datetime import timedelta

from memwing.application.graph_write_processor import GraphWriteProcessor
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.graph_backend import (
    GraphWriteBatchItemResult,
    GraphWriteBatchRequest,
    GraphWriteBatchResult,
    GraphWriteRequest,
)
from tests.integration.graph_write_worker_fixtures import (
    FakeGraphBackend,
    NOW,
    graph_job,
    memory_item,
    source_event,
    successful_graph_result,
)


def test_graph_write_processor_loads_inputs_calls_backend_and_materializes_links() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        job = graph_job(
            status="processing",
            locked_by="graph_worker_001",
            locked_at=NOW,
            lock_expires_at=NOW + timedelta(minutes=5),
            updated_at=NOW,
        )
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(job)

        backend = FakeGraphBackend(successful_graph_result())
        processor = GraphWriteProcessor(
            store,
            graph_backend=backend,
            lifecycle_transition=None,
            worker_id="graph_worker_001",
            lock_duration=timedelta(minutes=5),
            backend_timeout=timedelta(seconds=30),
        )

        result = await processor.process(job, now=NOW)
        async with store.transaction() as tx:
            links = await tx.memory_graph_links.list_by_memory("memory_001")

        assert result.link_count == 2
        assert backend.requests == (
            GraphWriteRequest(
                job=job,
                memory_item=memory_item(),
                source_events=(source_event(),),
            ),
        )
        assert {link.backend_object_id for link in links} == {"episode_001", "fact_001"}

    asyncio.run(scenario())


def test_graph_write_processor_batch_preserves_per_job_results() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        job = graph_job(
            status="processing",
            locked_by="graph_worker_001",
            locked_at=NOW,
            lock_expires_at=NOW + timedelta(minutes=5),
            updated_at=NOW,
        )
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(job)

        backend = FakeGraphBackend(successful_graph_result())
        processor = GraphWriteProcessor(
            store,
            graph_backend=backend,
            lifecycle_transition=None,
            worker_id="graph_worker_001",
            lock_duration=timedelta(minutes=5),
            backend_timeout=timedelta(seconds=30),
        )

        results = await processor.process_batch((job,), now=NOW)
        async with store.transaction() as tx:
            links = await tx.memory_graph_links.list_by_memory("memory_001")

        assert len(results) == 1
        assert results[0].job == job
        assert results[0].error is None
        assert results[0].result is not None
        assert results[0].result.link_count == 2
        assert {link.backend_object_id for link in links} == {"episode_001", "fact_001"}

    asyncio.run(scenario())


def test_graph_write_processor_splits_timed_out_batch_into_single_jobs() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        job_1 = graph_job(
            status="processing",
            locked_by="graph_worker_001",
            locked_at=NOW,
            lock_expires_at=NOW + timedelta(minutes=5),
            updated_at=NOW,
        )
        job_2 = replace(
            job_1,
            id="graph_job_002",
            memory_id="memory_002",
            source_event_ids=("source_002",),
            idempotency_key="graph:memory_002",
        )
        source_2 = replace(
            source_event(),
            id="source_002",
            raw_payload_hash="hash_002",
            runtime_event_idempotency_key="runtime-key-002",
        )
        memory_2 = replace(
            memory_item(),
            id="memory_002",
            source_event_ids=("source_002",),
            primary_source_event_id="source_002",
        )
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.source_events.insert_if_absent(source_2)
            await tx.memory_items.upsert(memory_item())
            await tx.memory_items.upsert(memory_2)
            await tx.graph_write_jobs.enqueue(job_1)
            await tx.graph_write_jobs.enqueue(job_2)

        backend = TimeoutThenSingleSuccessGraphBackend()
        processor = GraphWriteProcessor(
            store,
            graph_backend=backend,
            lifecycle_transition=None,
            worker_id="graph_worker_001",
            lock_duration=timedelta(minutes=5),
            backend_timeout=timedelta(seconds=30),
        )

        results = await processor.process_batch((job_1, job_2), now=NOW)

        async with store.transaction() as tx:
            links_1 = await tx.memory_graph_links.list_by_memory("memory_001")
            links_2 = await tx.memory_graph_links.list_by_memory("memory_002")

        assert [result.error for result in results] == [None, None]
        assert backend.batch_sizes == [2, 1, 1]
        assert len(links_1) == 2
        assert len(links_2) == 2

    asyncio.run(scenario())


class TimeoutThenSingleSuccessGraphBackend:
    def __init__(self) -> None:
        self.requests: tuple[GraphWriteRequest, ...] = ()
        self.batch_sizes: list[int] = []

    async def ingest_graph_jobs(self, request: GraphWriteBatchRequest) -> GraphWriteBatchResult:
        self.batch_sizes.append(len(request.requests))
        if len(request.requests) > 1:
            raise TimeoutError
        item_request = request.requests[0]
        return GraphWriteBatchResult(
            items=(
                GraphWriteBatchItemResult(
                    job_id=item_request.job.id,
                    result=await self.ingest_graph_job(item_request),
                    error_type=None,
                    error_message=None,
                    reason_code=None,
                    retryable=False,
                ),
            )
        )

    async def ingest_graph_job(self, request: GraphWriteRequest):
        self.requests = (*self.requests, request)
        base = successful_graph_result()
        fact_id = f"fact_{request.job.id}"
        return replace(
            base,
            facts=(
                replace(
                    base.facts[0],
                    fact_id=fact_id,
                    source_event_ids=(request.job.source_event_ids[0],),
                ),
            ),
            backend_episode_refs=(f"episode_{request.job.id}",),
            backend_fact_refs=(fact_id,),
        )
