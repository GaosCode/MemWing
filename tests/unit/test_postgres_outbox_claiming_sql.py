"""SQL-boundary tests using a fake connection; these do not execute Postgres."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from memwing.infrastructure.db.postgres import PostgresDataStore
from memwing.ports.event_store import OutboxLockOwnershipError

from tests.unit.postgres_store_fixtures import (
    FakePostgresConnection,
    outbox_job,
    outbox_job_row,
    source_event,
)


def test_postgres_claim_pending_uses_atomic_skip_locked_update() -> None:
    now = datetime(2026, 4, 28, tzinfo=UTC)
    claimed_job = replace(
        outbox_job(source_event()),
        status="processing",
        locked_at=now,
        locked_by="worker_b",
        lock_expires_at=now + timedelta(minutes=5),
    )
    connection = FakePostgresConnection(fetch_results=((outbox_job_row(claimed_job),),))

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            claimed = await tx.outbox_jobs.claim_pending(
                now=now,
                worker_id="worker_b",
                lock_duration=timedelta(minutes=5),
                limit=3,
            )

        assert claimed == (claimed_job,)

    asyncio.run(scenario())

    method, sql, params = connection.calls[0]
    assert method == "fetch"
    assert "WITH claim AS" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert sql.index("LIMIT %(limit)s") < sql.index("FOR UPDATE SKIP LOCKED")
    assert "status = 'processing' AND lock_expires_at <= %(now)s" in sql
    assert "locked_by = %(worker_id)s" in sql
    assert "lock_expires_at = %(lock_expires_at)s" in sql
    assert params["worker_id"] == "worker_b"
    assert params["lock_expires_at"] == now + timedelta(minutes=5)
    assert params["limit"] == 3


def test_postgres_complete_and_retry_require_lock_owner() -> None:
    now = datetime(2026, 4, 28, tzinfo=UTC)
    failed_job = replace(
        outbox_job(source_event()),
        status="pending",
        attempts=1,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error="handler failed",
        next_run_at=now + timedelta(seconds=30),
        updated_at=now,
    )
    connection = FakePostgresConnection(fetchrow_results=(None, outbox_job_row(failed_job)))

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            with pytest.raises(OutboxLockOwnershipError):
                await tx.outbox_jobs.mark_succeeded(
                    job_id="outbox_001",
                    locked_by="worker_b",
                    now=now,
                )
            updated = await tx.outbox_jobs.mark_failed(
                job_id="outbox_001",
                locked_by="worker_b",
                now=now,
                error="handler failed",
                retry_delay=timedelta(seconds=30),
            )

        assert updated == failed_job

    asyncio.run(scenario())

    succeeded_sql = connection.calls[0][1]
    failed_sql = connection.calls[1][1]
    assert "AND locked_by = %(locked_by)s" in succeeded_sql
    assert "AND locked_by = %(locked_by)s" in failed_sql
    assert "attempts + 1 >= max_attempts" in failed_sql
    assert "dead_letter" in failed_sql
