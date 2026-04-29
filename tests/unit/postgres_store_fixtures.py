"""Fake async connection fixtures for Postgres SQL-boundary tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime

from memwing.core.models import (
    AuditEvent,
    EvidenceChunk,
    GraphWriteJob,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryItem,
    MemoryPageVersion,
    MemoryRoute,
    MemoryStatus,
    MemoryVersion,
    OutboxJob,
    PageMemory,
    PageMemoryTopic,
    SourceEvent,
    WorkingMemoryEntry,
)


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
        actor_id="system",
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


def evidence_chunk_row(chunk: EvidenceChunk) -> dict[str, object]:
    return asdict(chunk)


def working_memory_entry_row(entry: WorkingMemoryEntry) -> dict[str, object]:
    return asdict(entry)


def memory_item_row(item: MemoryItem) -> dict[str, object]:
    return asdict(item)


def memory_version_row(version: MemoryVersion) -> dict[str, object]:
    return asdict(version)


def page_memory_row(page: PageMemory) -> dict[str, object]:
    row = asdict(page)
    row["topics_json"] = row.pop("topics")
    return row


def memory_page_version_row(version: MemoryPageVersion) -> dict[str, object]:
    row = asdict(version)
    row["topics_json"] = row.pop("topics")
    return row


def graph_write_job_row(job: GraphWriteJob) -> dict[str, object]:
    return asdict(job)


def memory_graph_link_row(link: MemoryGraphLink) -> dict[str, object]:
    return asdict(link)


def evidence_chunk() -> EvidenceChunk:
    source = source_event()
    return EvidenceChunk(
        id="chunk_001",
        source_event_id=source.id,
        project_memory_space_id=source.project_memory_space_id,
        group_id=source.group_id,
        thread_id=source.thread_id,
        shared_group_id=source.shared_group_id,
        chunk_text="Ship data foundation.",
        chunk_index=0,
        embedding_model=None,
        embedding_ref=None,
        embedding_vector=None,
        invalidated_at=None,
        created_at=source.created_at,
    )


def working_memory_entry() -> WorkingMemoryEntry:
    source = source_event()
    return WorkingMemoryEntry(
        id="working_001",
        source_event_id=source.id,
        project_memory_space_id=source.project_memory_space_id,
        group_id=source.group_id,
        thread_id=source.thread_id,
        shared_group_id=source.shared_group_id,
        content="Recent message.",
        token_count=4,
        sequence=12,
        flushed_at=None,
        created_at=source.created_at,
    )


def memory_item() -> MemoryItem:
    now = source_event().created_at
    return MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Demo scope",
        content="Demo scope remains Feishu plus OpenClaw.",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.CANDIDATE,
        event_time=now,
        valid_from=None,
        valid_to=None,
        original_score=0.82,
        half_life_days=30,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=now,
        activated_at=None,
        updated_at=now,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def memory_version() -> MemoryVersion:
    now = source_event().created_at
    return MemoryVersion(
        id="memory_version_001",
        memory_id="memory_001",
        version=1,
        title="Demo scope",
        content="Demo scope remains Feishu plus OpenClaw.",
        summary=None,
        status=MemoryStatus.CANDIDATE,
        source_event_ids=("source_001",),
        changed_by="system",
        change_reason="long_term_filter_candidate",
        created_at=now,
    )


def page_memory() -> PageMemory:
    now = source_event().created_at
    return PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Thread mainline",
        brief="The thread is validating memory lanes.",
        topics=(page_memory_topic(),),
        open_questions=("Which lane owns recall warnings?",),
        next_steps=("Wire the page memory worker.",),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
        version=1,
        needs_rebuild=False,
        created_at=now,
        updated_at=now,
    )


def memory_page_version() -> MemoryPageVersion:
    now = source_event().created_at
    return MemoryPageVersion(
        id="page_version_001",
        page_id="page_001",
        version=1,
        title="Thread mainline",
        brief="The thread is validating memory lanes.",
        topics=(page_memory_topic(),),
        open_questions=("Which lane owns recall warnings?",),
        next_steps=("Wire the page memory worker.",),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
        changed_by="system",
        change_reason="initial_rebuild",
        created_at=now,
    )


def page_memory_topic() -> PageMemoryTopic:
    return PageMemoryTopic(
        title="Memory lane validation",
        summary="The thread is validating derived memory lanes.",
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
    )


def graph_write_job() -> GraphWriteJob:
    now = source_event().created_at
    return GraphWriteJob(
        id="graph_job_001",
        backend="graphiti",
        project_memory_space_id="project_001",
        thread_id="thread_001",
        saga_id=None,
        memory_id="memory_001",
        source_event_ids=("source_001",),
        route=MemoryRoute.GRAPH,
        status="pending",
        idempotency_key="graph:memory_001",
        attempts=0,
        max_attempts=3,
        priority=100,
        next_run_at=now,
        dead_letter_reason=None,
        last_error=None,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        created_at=now,
        updated_at=now,
    )


def memory_graph_link() -> MemoryGraphLink:
    now = source_event().created_at
    return MemoryGraphLink(
        id="graph_link_001",
        backend="graphiti",
        memory_id="memory_001",
        source_event_id="source_001",
        project_memory_space_id="project_001",
        backend_space_id="project_001",
        backend_object_type="entity_edge",
        backend_object_id="edge_001",
        link_type="fact",
        created_at=now,
    )
