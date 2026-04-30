import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.core.models import GraphWriteJob, MemoryRoute
from memwing.infrastructure.db.in_memory import InMemoryDataStore


NOW = datetime(2026, 4, 28, tzinfo=UTC)


def test_expired_processing_graph_job_can_be_reclaimed_by_another_worker() -> None:
    store = InMemoryDataStore()
    store.add_graph_write_job(
        _job(
            "graph_job_001",
            status="processing",
            locked_by="worker_a",
            lock_expires_at=NOW - timedelta(seconds=1),
        )
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            claimed = await tx.graph_write_jobs.claim_pending(
                now=NOW,
                worker_id="worker_b",
                lock_duration=timedelta(minutes=5),
                limit=1,
            )

        assert claimed == (
            replace(
                _job("graph_job_001"),
                status="processing",
                locked_at=NOW,
                locked_by="worker_b",
                lock_expires_at=NOW + timedelta(minutes=5),
                updated_at=NOW,
            ),
        )
        assert store.graph_write_jobs[0].locked_by == "worker_b"

    asyncio.run(scenario())


def test_unexpired_processing_graph_job_blocks_same_thread_group_claim() -> None:
    store = InMemoryDataStore()
    store.add_graph_write_job(
        _job(
            "graph_job_001",
            status="processing",
            locked_by="worker_a",
            lock_expires_at=NOW + timedelta(minutes=5),
        )
    )
    store.add_graph_write_job(_job("graph_job_002"))
    store.add_graph_write_job(_job("graph_job_003", project_memory_space_id="project_002"))

    async def scenario() -> None:
        async with store.transaction() as tx:
            claimed = await tx.graph_write_jobs.claim_pending(
                now=NOW,
                worker_id="worker_b",
                lock_duration=timedelta(minutes=5),
                limit=3,
            )

        assert tuple(job.id for job in claimed) == ("graph_job_003",)
        assert store.graph_write_jobs[1].status == "pending"

    asyncio.run(scenario())


def test_unexpired_processing_graph_job_blocks_same_project_claim() -> None:
    store = InMemoryDataStore()
    store.add_graph_write_job(
        _job(
            "graph_job_001",
            status="processing",
            locked_by="worker_a",
            lock_expires_at=NOW + timedelta(minutes=5),
        )
    )
    store.add_graph_write_job(_job("graph_job_002", thread_id="thread_002"))
    store.add_graph_write_job(_job("graph_job_003", project_memory_space_id="project_002"))

    async def scenario() -> None:
        async with store.transaction() as tx:
            claimed = await tx.graph_write_jobs.claim_pending(
                now=NOW,
                worker_id="worker_b",
                lock_duration=timedelta(minutes=5),
                limit=3,
            )

        assert tuple(job.id for job in claimed) == ("graph_job_003",)
        assert store.graph_write_jobs[1].status == "pending"

    asyncio.run(scenario())


def test_graph_claim_limit_zero_claims_no_jobs() -> None:
    store = InMemoryDataStore()
    store.add_graph_write_job(_job("graph_job_001"))

    async def scenario() -> None:
        async with store.transaction() as tx:
            claimed = await tx.graph_write_jobs.claim_pending(
                now=NOW,
                worker_id="worker_b",
                lock_duration=timedelta(minutes=5),
                limit=0,
            )

        assert claimed == ()
        assert store.graph_write_jobs[0].status == "pending"

    asyncio.run(scenario())


def _job(
    job_id: str,
    *,
    project_memory_space_id: str = "project_001",
    thread_id: str | None = "thread_001",
    status: str = "pending",
    locked_by: str | None = None,
    lock_expires_at: datetime | None = None,
) -> GraphWriteJob:
    return GraphWriteJob(
        id=job_id,
        backend="graphiti",
        project_memory_space_id=project_memory_space_id,
        thread_id=thread_id,
        saga_id=None,
        memory_id=f"memory_{job_id}",
        source_event_ids=(f"source_{job_id}",),
        route=MemoryRoute.GRAPH,
        status=status,
        idempotency_key=f"graph:{job_id}",
        attempts=0,
        max_attempts=3,
        priority=100,
        next_run_at=NOW,
        dead_letter_reason=None,
        last_error=None,
        locked_at=NOW if locked_by else None,
        locked_by=locked_by,
        lock_expires_at=lock_expires_at,
        created_at=NOW,
        updated_at=NOW,
    )
