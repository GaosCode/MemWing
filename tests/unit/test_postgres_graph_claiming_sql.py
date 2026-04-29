import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.infrastructure.db.postgres import PostgresDataStore

from tests.unit.postgres_store_fixtures import (
    FakePostgresConnection,
    graph_write_job,
    graph_write_job_row,
)


def test_postgres_graph_claim_pending_enforces_group_backpressure() -> None:
    now = datetime(2026, 4, 28, tzinfo=UTC)
    claimed_job = replace(
        graph_write_job(),
        status="processing",
        locked_at=now,
        locked_by="worker_b",
        lock_expires_at=now + timedelta(minutes=5),
    )
    connection = FakePostgresConnection(fetch_results=((graph_write_job_row(claimed_job),),))

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            claimed = await tx.graph_write_jobs.claim_pending(
                now=now,
                worker_id="worker_b",
                lock_duration=timedelta(minutes=5),
                limit=3,
            )

        assert claimed == (claimed_job,)

    asyncio.run(scenario())

    method, sql, params = connection.calls[0]
    assert method == "fetch"
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "NOT EXISTS" in sql
    assert "active.status = 'processing'" in sql
    assert "active.lock_expires_at IS NULL OR active.lock_expires_at > %(now)s" in sql
    assert "active.thread_id IS NOT DISTINCT FROM job.thread_id" in sql
    assert "active.saga_id IS NOT DISTINCT FROM job.saga_id" in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "PARTITION BY job.project_memory_space_id, job.thread_id, job.saga_id" in sql
    assert "group_rank = 1" in sql
    assert params["worker_id"] == "worker_b"
    assert params["lock_expires_at"] == now + timedelta(minutes=5)
    assert params["limit"] == 3
