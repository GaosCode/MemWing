import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from memwing.core.models import OutboxJob
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.event_store import OutboxLockOwnershipError


def _job(
    job_id: str,
    *,
    job_type: str = "evidence.index_source_event",
    aggregate_key: str = "source_001",
    status: str = "pending",
    locked_by: str | None = None,
    lock_expires_at: datetime | None = None,
) -> OutboxJob:
    now = datetime(2026, 4, 28, tzinfo=UTC)
    return OutboxJob(
        id=job_id,
        project_memory_space_id="project_001",
        source_event_id="source_001",
        job_type=job_type,
        payload_json={"source_event_id": "source_001"},
        status=status,
        idempotency_key=f"outbox:{job_id}",
        aggregate_key=aggregate_key,
        attempts=0,
        max_attempts=3,
        priority=10,
        next_run_at=now,
        locked_at=now if locked_by else None,
        locked_by=locked_by,
        lock_expires_at=lock_expires_at,
        last_error=None,
        dead_letter_reason=None,
        created_at=now,
        updated_at=now,
    )


def test_claim_assigns_locked_by_and_requires_owner_to_complete() -> None:
    store = InMemoryDataStore()
    store.add_outbox_job(_job("job_001"))
    now = datetime(2026, 4, 28, tzinfo=UTC)

    async def scenario() -> None:
        async with store.transaction() as tx:
            claimed = await tx.outbox_jobs.claim_pending(
                now=now,
                worker_id="worker_a",
                lock_duration=timedelta(minutes=5),
                limit=1,
            )
            assert claimed[0].locked_by == "worker_a"

        async with store.transaction() as tx:
            with pytest.raises(OutboxLockOwnershipError):
                await tx.outbox_jobs.mark_succeeded(
                    job_id="job_001",
                    locked_by="worker_b",
                    now=now,
                )

    asyncio.run(scenario())


def test_expired_processing_job_can_be_reclaimed_by_another_worker() -> None:
    store = InMemoryDataStore()
    now = datetime(2026, 4, 28, tzinfo=UTC)
    store.add_outbox_job(
        _job(
            "job_001",
            status="processing",
            locked_by="worker_a",
            lock_expires_at=now - timedelta(seconds=1),
        )
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            claimed = await tx.outbox_jobs.claim_pending(
                now=now,
                worker_id="worker_b",
                lock_duration=timedelta(minutes=5),
                limit=1,
            )

        assert claimed[0].locked_by == "worker_b"
        assert store.outbox_jobs[0].locked_by == "worker_b"
        assert store.outbox_jobs[0].status == "processing"

    asyncio.run(scenario())


def test_claim_pending_for_project_and_type_only_claims_matching_job_type() -> None:
    store = InMemoryDataStore()
    now = datetime(2026, 4, 28, tzinfo=UTC)
    store.add_outbox_job(_job("job_001", job_type="evidence.index_source_event"))
    store.add_outbox_job(_job("job_002", job_type="long_term_filter.classify"))

    async def scenario() -> None:
        async with store.transaction() as tx:
            claimed = await tx.outbox_jobs.claim_pending_for_project_and_type(
                project_memory_space_id="project_001",
                job_type="long_term_filter.classify",
                now=now,
                worker_id="worker_ltf",
                lock_duration=timedelta(minutes=5),
                limit=10,
            )

        assert tuple(job.id for job in claimed) == ("job_002",)
        assert {job.id: job.status for job in store.outbox_jobs} == {
            "job_001": "pending",
            "job_002": "processing",
        }
        assert store.outbox_jobs[1].locked_by == "worker_ltf"

    asyncio.run(scenario())


def test_claim_pending_for_project_type_and_aggregate_only_claims_matching_scope() -> None:
    store = InMemoryDataStore()
    now = datetime(2026, 4, 28, tzinfo=UTC)
    store.add_outbox_job(
        _job(
            "job_001",
            job_type="long_term_filter.classify",
            aggregate_key="long_term_filter:project_001:group_001:thread_001:",
        )
    )
    store.add_outbox_job(
        _job(
            "job_002",
            job_type="long_term_filter.classify",
            aggregate_key="long_term_filter:project_001:group_001:thread_002:",
        )
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            claimed = await tx.outbox_jobs.claim_pending_for_project_type_and_aggregate(
                project_memory_space_id="project_001",
                job_type="long_term_filter.classify",
                aggregate_key="long_term_filter:project_001:group_001:thread_001:",
                now=now,
                worker_id="worker_ltf",
                lock_duration=timedelta(minutes=5),
                limit=10,
            )

        assert tuple(job.id for job in claimed) == ("job_001",)
        assert {job.id: job.status for job in store.outbox_jobs} == {
            "job_001": "processing",
            "job_002": "pending",
        }

    asyncio.run(scenario())
