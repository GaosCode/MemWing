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
    assert "active.serialization_key = job.serialization_key" in sql
    assert "active.status = 'processing'" in sql
    assert "active.lock_expires_at IS NULL OR active.lock_expires_at > %(now)s" in sql
    assert "active_project_keys" in sql
    assert "COUNT(DISTINCT serialization_key)" in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "PARTITION BY job.serialization_key" in sql
    assert "PARTITION BY claimable.project_memory_space_id" in sql
    assert "project_key_rank" in sql
    assert "CASE WHEN job.status = 'processing' THEN 0 ELSE 1 END" in sql
    assert "max_project_concurrency" in params
    assert params["worker_id"] == "worker_b"
    assert params["lock_expires_at"] == now + timedelta(minutes=5)
    assert params["limit"] == 3


def test_postgres_graph_extend_lock_requires_current_owner() -> None:
    now = datetime(2026, 4, 28, tzinfo=UTC)
    updated_job = replace(
        graph_write_job(),
        status="processing",
        locked_at=now,
        locked_by="worker_b",
        lock_expires_at=now + timedelta(minutes=5),
    )
    connection = FakePostgresConnection(fetchrow_results=(graph_write_job_row(updated_job),))

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            updated = await tx.graph_write_jobs.extend_lock(
                job_id=updated_job.id,
                locked_by="worker_b",
                now=now,
                lock_duration=timedelta(minutes=5),
            )

        assert updated == updated_job

    asyncio.run(scenario())

    method, sql, params = connection.calls[0]
    assert method == "fetchrow"
    assert "UPDATE graph_write_jobs" in sql
    assert "lock_expires_at = %(lock_expires_at)s" in sql
    assert "AND status = 'processing'" in sql
    assert "AND locked_by = %(locked_by)s" in sql
    assert params["job_id"] == updated_job.id
    assert params["locked_by"] == "worker_b"
    assert params["lock_expires_at"] == now + timedelta(minutes=5)


def test_postgres_graph_mark_dead_letter_requires_current_owner() -> None:
    now = datetime(2026, 4, 28, tzinfo=UTC)
    updated_job = replace(
        graph_write_job(),
        status="dead_letter",
        attempts=1,
        last_error="ProviderPermanentFailure",
        dead_letter_reason="ProviderPermanentFailure",
    )
    connection = FakePostgresConnection(fetchrow_results=(graph_write_job_row(updated_job),))

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            updated = await tx.graph_write_jobs.mark_dead_letter(
                job_id=updated_job.id,
                locked_by="worker_b",
                now=now,
                error="ProviderPermanentFailure",
            )

        assert updated == updated_job

    asyncio.run(scenario())

    method, sql, params = connection.calls[0]
    assert method == "fetchrow"
    assert "UPDATE graph_write_jobs" in sql
    assert "status = 'dead_letter'" in sql
    assert "attempts = attempts + 1" in sql
    assert "dead_letter_reason = %(last_error)s" in sql
    assert "AND status = 'processing'" in sql
    assert "AND locked_by = %(locked_by)s" in sql
    assert params["job_id"] == updated_job.id
    assert params["locked_by"] == "worker_b"
    assert params["last_error"] == "ProviderPermanentFailure"
