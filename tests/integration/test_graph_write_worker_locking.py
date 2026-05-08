import asyncio

import pytest

from memwing.core.models import MemoryStatus
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.event_store import OutboxLockOwnershipError
from memwing.workers.graph_write_worker import GraphWriteWorker
from tests.integration.graph_write_worker_fixtures import (
    FakeGraphBackend,
    FakeLifecycleTransition,
    NOW,
    ReclaimingGraphBackend,
    graph_job,
    graph_result_with_invalidated_fact,
    graph_result_with_two_invalidated_facts,
    invalidated_memory_item,
    invalidated_source_event,
    memory_item,
    source_event,
)


def test_graph_write_worker_lost_lock_does_not_write_links_or_lifecycle_side_effects() -> None:
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
            graph_backend=ReclaimingGraphBackend(store, graph_result),
            lifecycle_transition=lifecycle,
            worker_id="graph_worker_001",
        )

        with pytest.raises(OutboxLockOwnershipError):
            await worker.run_once(now=NOW)

        async with store.transaction() as tx:
            invalidated = await tx.memory_items.get("memory_old")

        assert invalidated is not None
        assert invalidated.status is MemoryStatus.ACTIVE
        assert lifecycle.requests == ()
        assert store.memory_graph_links == ()
        assert store.graph_write_jobs[0].locked_by == "graph_worker_002"
        stages = tuple(event.stage for event in store.audit_events)
        assert "graph_write.backend.started" in stages
        assert "graph_write.succeeded" not in stages
        assert "graph_write.retry" not in stages
        assert "graph_write.dead_letter" not in stages
        lock_lost_events = tuple(
            event for event in store.audit_events if event.stage == "graph_write.lock_lost"
        )
        assert len(lock_lost_events) == 1
        assert lock_lost_events[0].reason_code == "lock_ownership_lost"
        assert lock_lost_events[0].reason_text == "OutboxLockOwnershipError"

    asyncio.run(scenario())


def test_graph_write_worker_stops_lifecycle_invalidations_after_lost_lock() -> None:
    store = InMemoryDataStore()
    graph_result = graph_result_with_two_invalidated_facts()

    async def scenario() -> None:
        async with store.transaction() as tx:
            for event in (
                source_event(),
                invalidated_source_event(),
                invalidated_source_event("source_older"),
            ):
                await tx.source_events.insert_if_absent(event)
            for item in (
                memory_item(),
                invalidated_memory_item(),
                invalidated_memory_item("memory_older", "source_older"),
            ):
                await tx.memory_items.upsert(item)
            await tx.graph_write_jobs.enqueue(graph_job())

        lifecycle = FakeLifecycleTransition(store, reclaim_after_first=True)
        worker = GraphWriteWorker(
            store,
            graph_backend=FakeGraphBackend(graph_result),
            lifecycle_transition=lifecycle,
            worker_id="graph_worker_001",
        )

        with pytest.raises(OutboxLockOwnershipError):
            await worker.run_once(now=NOW)

        async with store.transaction() as tx:
            first = await tx.memory_items.get("memory_old")
            second = await tx.memory_items.get("memory_older")

        assert first is not None
        assert second is not None
        assert first.status is MemoryStatus.NEEDS_REVIEW
        assert second.status is MemoryStatus.ACTIVE
        assert [request.memory_id for request in lifecycle.requests] == ["memory_old"]
        assert store.memory_graph_links == ()
        assert store.graph_write_jobs[0].locked_by == "graph_worker_002"

    asyncio.run(scenario())
