import asyncio

from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import MemoryStatus
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.lifecycle_transition import LifecycleTransitionRequest
from memwing.workers.graph_write_worker import GraphWriteWorker
from tests.integration.graph_write_worker_fixtures import (
    FakeGraphBackend,
    FakeLifecycleTransition,
    NOW,
    graph_job,
    graph_result_with_invalidated_fact,
    invalidated_memory_item,
    invalidated_source_event,
    memory_item,
    source_event,
)


def test_graph_write_worker_marks_invalidated_fact_memories_needs_review() -> None:
    store = InMemoryDataStore()
    invalidated_source = invalidated_source_event()
    invalidated_memory = invalidated_memory_item()
    graph_result = graph_result_with_invalidated_fact()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.source_events.insert_if_absent(invalidated_source)
            await tx.memory_items.upsert(memory_item())
            await tx.memory_items.upsert(invalidated_memory)
            await tx.graph_write_jobs.enqueue(graph_job())

        lifecycle = FakeLifecycleTransition(store)
        worker = GraphWriteWorker(
            store,
            graph_backend=FakeGraphBackend(graph_result),
            lifecycle_transition=lifecycle,
            worker_id="graph_worker_001",
        )

        result = await worker.run_once(now=NOW)

        async with store.transaction() as tx:
            updated = await tx.memory_items.get("memory_old")

        assert result.succeeded == 1
        assert updated is not None
        assert updated.status is MemoryStatus.NEEDS_REVIEW
        assert lifecycle.requests == (
            LifecycleTransitionRequest(
                memory_id="memory_old",
                action=LifecycleAction.MARK_NEEDS_REVIEW,
                actor_id="graph_write_worker",
                reason="graph fact invalidated",
                idempotency_key="graph:graph_job_001:invalidated:memory_old",
                trace_id="graph_write:graph_job_001",
                now=NOW,
            ),
        )
        assert store.audit_events[-1].stage == "graph_write.succeeded"

    asyncio.run(scenario())
