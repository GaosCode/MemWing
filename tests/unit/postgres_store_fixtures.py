"""Fake async connection fixtures for Postgres SQL-boundary tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime

from memwing.core.models import AuditEvent, OutboxJob, SourceEvent


class FakeTransaction:
    def __init__(self, connection: FakePostgresConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> None:
        self._connection.transaction_enters += 1

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self._connection.transaction_exits += 1
        return False


class FakePostgresConnection:
    def __init__(
        self,
        *,
        fetchrow_results: tuple[Mapping[str, object] | None, ...] = (),
        fetch_results: tuple[tuple[Mapping[str, object], ...], ...] = (),
    ) -> None:
        self.fetchrow_results = list(fetchrow_results)
        self.fetch_results = list(fetch_results)
        self.calls: list[tuple[str, str, Mapping[str, object]]] = []
        self.transaction_enters = 0
        self.transaction_exits = 0

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def fetchrow(self, sql: str, params: Mapping[str, object]) -> Mapping[str, object] | None:
        self.calls.append(("fetchrow", sql, params))
        if not self.fetchrow_results:
            raise AssertionError(f"unexpected fetchrow: {sql}")
        return self.fetchrow_results.pop(0)

    async def fetch(self, sql: str, params: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
        self.calls.append(("fetch", sql, params))
        if not self.fetch_results:
            raise AssertionError(f"unexpected fetch: {sql}")
        return self.fetch_results.pop(0)


def source_event() -> SourceEvent:
    now = datetime(2026, 4, 28, tzinfo=UTC)
    return SourceEvent(
        id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content="Ship data foundation.",
        content_preview="Ship data foundation.",
        source_url=None,
        event_time=now,
        raw_payload_hash="hash_001",
        metadata={"message_id": "message_001"},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=now,
        runtime_event_idempotency_key="runtime-key-001",
    )


def audit_event(source: SourceEvent) -> AuditEvent:
    return AuditEvent(
        id="audit_001",
        trace_id="trace_001",
        entity_type="source_event",
        entity_id=source.id,
        stage="remember_event.captured",
        input_ref=source.id,
        output_ref=None,
        decision="accepted",
        reason_code=None,
        reason_text=None,
        source_event_ids=(source.id,),
        latency_ms=None,
        created_at=source.created_at,
    )


def outbox_job(source: SourceEvent) -> OutboxJob:
    now = source.created_at
    return OutboxJob(
        id="outbox_001",
        project_memory_space_id=source.project_memory_space_id,
        source_event_id=source.id,
        job_type="evidence.index_source_event",
        payload_json={"source_event_id": source.id},
        status="pending",
        idempotency_key="evidence.index_source_event:source_001",
        aggregate_key=source.id,
        attempts=0,
        max_attempts=3,
        priority=100,
        next_run_at=now,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error=None,
        dead_letter_reason=None,
        created_at=now,
        updated_at=now,
    )


def source_event_row(source: SourceEvent) -> dict[str, object]:
    row = asdict(source)
    row["metadata_json"] = row.pop("metadata")
    return row


def audit_event_row(audit: AuditEvent) -> dict[str, object]:
    return asdict(audit)


def outbox_job_row(job: OutboxJob) -> dict[str, object]:
    return asdict(job)
