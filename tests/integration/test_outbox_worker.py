import asyncio
from datetime import UTC, datetime, timedelta

from memwing.core.models import OutboxJob
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.workers.outbox_worker import OutboxWorker


def _job(job_id: str, *, max_attempts: int = 3) -> OutboxJob:
    now = datetime(2026, 4, 28, tzinfo=UTC)
    return OutboxJob(
        id=job_id,
        project_memory_space_id="project_001",
        source_event_id="source_001",
        job_type="evidence.index_source_event",
        payload_json={"source_event_id": "source_001"},
        status="pending",
        idempotency_key=f"outbox:{job_id}",
        aggregate_key="source_001",
        attempts=0,
        max_attempts=max_attempts,
        priority=10,
        next_run_at=now,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error=None,
        dead_letter_reason=None,
        created_at=now,
        updated_at=now,
    )


def test_outbox_worker_claims_and_marks_success_with_audit() -> None:
    store = InMemoryDataStore()
    store.add_outbox_job(_job("job_001"))
    handled: list[str] = []
    worker = OutboxWorker(
        store,
        worker_id="worker_001",
        handlers={"evidence.index_source_event": lambda job: _record(handled, job.id)},
    )

    result = asyncio.run(worker.run_once(now=datetime(2026, 4, 28, tzinfo=UTC)))

    assert result.claimed == 1
    assert result.succeeded == 1
    assert handled == ["job_001"]
    assert store.outbox_jobs[0].status == "succeeded"
    assert store.audit_events[-1].stage == "outbox.succeeded"


def test_outbox_worker_retries_failed_job_without_losing_lock_semantics() -> None:
    store = InMemoryDataStore()
    store.add_outbox_job(_job("job_001"))
    worker = OutboxWorker(
        store,
        worker_id="worker_001",
        handlers={"evidence.index_source_event": _fail_once_then_succeed()},
        retry_delay=timedelta(0),
    )
    now = datetime(2026, 4, 28, tzinfo=UTC)

    first = asyncio.run(worker.run_once(now=now))
    second = asyncio.run(worker.run_once(now=now))

    assert first.retried == 1
    assert second.succeeded == 1
    assert store.outbox_jobs[0].attempts == 1
    assert store.outbox_jobs[0].status == "succeeded"
    assert [event.stage for event in store.audit_events] == [
        "outbox.failed",
        "outbox.succeeded",
    ]


def test_outbox_worker_dead_letters_after_max_attempts() -> None:
    store = InMemoryDataStore()
    store.add_outbox_job(_job("job_001", max_attempts=1))
    worker = OutboxWorker(
        store,
        worker_id="worker_001",
        handlers={"evidence.index_source_event": _always_fail},
        retry_delay=timedelta(0),
    )

    result = asyncio.run(worker.run_once(now=datetime(2026, 4, 28, tzinfo=UTC)))

    assert result.dead_lettered == 1
    assert store.outbox_jobs[0].status == "dead_letter"
    assert store.outbox_jobs[0].dead_letter_reason == "RuntimeError"
    assert store.audit_events[-1].stage == "outbox.dead_letter"
    assert store.audit_events[-1].reason_code == "unexpected_failure"
    assert store.audit_events[-1].reason_text == "RuntimeError"


async def _record(handled: list[str], job_id: str) -> None:
    handled.append(job_id)


def _fail_once_then_succeed():
    attempts = 0

    async def handler(_: OutboxJob) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("handler failed")

    return handler


async def _always_fail(_: OutboxJob) -> None:
    raise RuntimeError("handler failed")
