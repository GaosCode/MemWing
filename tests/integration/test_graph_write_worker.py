import asyncio
from datetime import timedelta

from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.graph_backend import GraphWriteRequest
from memwing.workers.graph_write_worker import GraphWriteWorker
from tests.integration.graph_write_worker_fixtures import (
    FakeGraphBackend,
    NOW,
    graph_job,
    memory_item,
    source_event,
    successful_graph_result,
)


def test_graph_write_worker_ingests_job_writes_links_and_audit() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job())

        backend = FakeGraphBackend(successful_graph_result())
        worker = GraphWriteWorker(
            store,
            graph_backend=backend,
            worker_id="graph_worker_001",
        )

        result = await worker.run_once(now=NOW)

        async with store.transaction() as tx:
            links = await tx.memory_graph_links.list_by_memory("memory_001")

        assert result.claimed == 1
        assert result.succeeded == 1
        assert backend.requests == (
            GraphWriteRequest(
                job=graph_job(
                    status="processing",
                    locked_by="graph_worker_001",
                    locked_at=NOW,
                    lock_expires_at=NOW + timedelta(minutes=5),
                    updated_at=NOW,
                ),
                memory_item=memory_item(),
                source_events=(source_event(),),
            ),
        )
        assert len(links) == 2
        assert {link.backend_object_id for link in links} == {"episode_001", "fact_001"}
        assert {link.link_type for link in links} == {"episode", "fact"}
        assert store.audit_events[-1].stage == "graph_write.succeeded"
        assert store.audit_events[-1].input_ref == "graph_job_001"
        assert store.audit_events[-1].output_ref == "memory_graph_links:2"
        assert "Decision source text." not in (store.audit_events[-1].reason_text or "")

    asyncio.run(scenario())
