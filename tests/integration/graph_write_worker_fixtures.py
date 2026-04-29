from datetime import UTC, datetime

from memwing.core.models import (
    GraphFact,
    GraphWriteJob,
    GraphWriteResult,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    SourceEvent,
)


NOW = datetime(2026, 4, 28, tzinfo=UTC)


def source_event() -> SourceEvent:
    return SourceEvent(
        id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content="Decision source text.",
        content_preview="Decision source text.",
        source_url=None,
        event_time=NOW,
        raw_payload_hash="hash_001",
        metadata={"message_id": "message_001"},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
        runtime_event_idempotency_key="runtime-key-001",
    )


def memory_item() -> MemoryItem:
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
        event_time=NOW,
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
        created_at=NOW,
        activated_at=None,
        updated_at=NOW,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def successful_graph_result() -> GraphWriteResult:
    return GraphWriteResult(
        backend="graphiti",
        facts=(
            GraphFact(
                backend="graphiti",
                fact_id="fact_001",
                fact_text="Demo scope remains Feishu plus OpenClaw.",
                source_event_ids=("source_001",),
                valid_from=None,
                valid_to=None,
                invalidated_at=None,
                confidence=0.91,
                metadata={},
            ),
        ),
        invalidated_facts=(),
        backend_episode_refs=("episode_001",),
        backend_fact_refs=("fact_001",),
    )


def graph_job(
    *,
    status: str = "pending",
    max_attempts: int = 3,
    locked_by: str | None = None,
    locked_at: datetime | None = None,
    lock_expires_at: datetime | None = None,
    updated_at: datetime = NOW,
) -> GraphWriteJob:
    return GraphWriteJob(
        id="graph_job_001",
        backend="graphiti",
        project_memory_space_id="project_001",
        thread_id="thread_001",
        saga_id=None,
        memory_id="memory_001",
        source_event_ids=("source_001",),
        route=MemoryRoute.GRAPH,
        status=status,
        idempotency_key="graph:memory_001",
        attempts=0,
        max_attempts=max_attempts,
        priority=100,
        next_run_at=NOW,
        dead_letter_reason=None,
        last_error=None,
        locked_at=locked_at,
        locked_by=locked_by,
        lock_expires_at=lock_expires_at,
        created_at=NOW,
        updated_at=updated_at,
    )
