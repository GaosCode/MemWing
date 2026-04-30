import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import uuid

from memwing.api.agent_runtime import AgentMemoryQuery, AgentMemorySearchResult
from memwing.core.models import AuditEvent
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
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.graph_backend import GraphWriteRequest
from memwing.ports.lifecycle_transition import LifecycleTransitionRequest, LifecycleTransitionResult


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


class FakeGraphBackend:
    def __init__(self, result: GraphWriteResult) -> None:
        self._result = result
        self.requests: tuple[GraphWriteRequest, ...] = ()

    async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        self.requests = (*self.requests, request)
        return self._result

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class FailingGraphBackend:
    def __init__(self, error: str) -> None:
        self._error = error

    async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        raise RuntimeError(self._error)

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class HangingGraphBackend:
    async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        await asyncio.Event().wait()

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class ReclaimingGraphBackend:
    def __init__(self, store: InMemoryDataStore, result: GraphWriteResult) -> None:
        self._store = store
        self._result = result

    async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        async with self._store.transaction() as tx:
            await tx.graph_write_jobs.claim_pending(
                now=NOW + timedelta(minutes=5, seconds=1),
                worker_id="graph_worker_002",
                lock_duration=timedelta(minutes=5),
                limit=1,
            )
        return self._result

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class FakeLifecycleTransition:
    def __init__(
        self,
        store: InMemoryDataStore,
        *,
        reclaim_after_first: bool = False,
    ) -> None:
        self._store = store
        self._reclaim_after_first = reclaim_after_first
        self.requests: tuple[LifecycleTransitionRequest, ...] = ()

    async def transition(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransitionResult:
        self.requests = (*self.requests, request)
        async with self._store.transaction() as tx:
            memory = await tx.memory_items.get(request.memory_id)
            assert memory is not None
            updated = replace(
                memory,
                status=MemoryStatus.NEEDS_REVIEW,
                updated_at=request.now,
            )
            await tx.memory_items.upsert(updated)

        audit_event = AuditEvent(
            id=str(uuid.uuid4()),
            trace_id=request.trace_id,
            entity_type="memory_item",
            entity_id=request.memory_id,
            stage="memory.lifecycle_transition",
            input_ref=request.memory_id,
            output_ref=updated.status,
            decision=request.action.value,
            reason_code=None,
            reason_text=request.reason,
            source_event_ids=updated.source_event_ids,
            latency_ms=None,
            created_at=request.now,
            actor_id=request.actor_id,
        )
        if self._reclaim_after_first and len(self.requests) == 1:
            async with self._store.transaction() as tx:
                await tx.graph_write_jobs.claim_pending(
                    now=NOW + timedelta(minutes=5, seconds=1),
                    worker_id="graph_worker_002",
                    lock_duration=timedelta(minutes=5),
                    limit=1,
                )
        return LifecycleTransitionResult(
            memory_item=updated,
            previous_status=memory.status,
            audit_event=audit_event,
        )


def invalidated_source_event(source_event_id: str = "source_old") -> SourceEvent:
    return replace(source_event(), id=source_event_id, content="Old decision.")


def invalidated_memory_item(
    memory_id: str = "memory_old",
    source_event_id: str = "source_old",
) -> MemoryItem:
    return replace(
        memory_item(),
        id=memory_id,
        source_event_ids=(source_event_id,),
        primary_source_event_id=source_event_id,
        status=MemoryStatus.ACTIVE,
    )


def graph_result_with_invalidated_fact() -> GraphWriteResult:
    return replace(
        successful_graph_result(),
        invalidated_facts=(
            GraphFact(
                backend="graphiti",
                fact_id="fact_old",
                fact_text="Old decision.",
                source_event_ids=("source_old",),
                valid_from=None,
                valid_to=NOW,
                invalidated_at=NOW,
                confidence=0.8,
                metadata={},
            ),
        ),
    )


def graph_result_with_two_invalidated_facts() -> GraphWriteResult:
    result = graph_result_with_invalidated_fact()
    invalidated_fact = result.invalidated_facts[0]
    return replace(
        result,
        invalidated_facts=(
            invalidated_fact,
            replace(
                invalidated_fact,
                fact_id="fact_older",
                fact_text="Older decision.",
                source_event_ids=("source_older",),
            ),
        ),
    )
