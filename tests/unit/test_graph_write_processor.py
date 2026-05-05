import asyncio
from datetime import timedelta

from memwing.application.graph_write_processor import GraphWriteProcessor
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.graph_backend import GraphWriteRequest
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
