from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from memwing.application.source_redaction_service import (
    REDACTED_SOURCE_CONTENT,
    SourceRedactionCommand,
    SourceRedactionService,
)
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult
from memwing.core.models import (
    EvidenceChunk,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    PageMemory,
    PageMemoryTopic,
    PushCandidate,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore


NOW = datetime(2026, 4, 30, tzinfo=UTC)
SCOPE = EffectiveScope(
    project_memory_space_id="project_001",
    group_ids=("group_001",),
    thread_id="thread_001",
    shared_group_id=None,
    safe_mode_enabled=True,
    cross_group_allowed=False,
)


def test_source_redaction_invalidates_derived_layers_and_audits_graph_marker_warning() -> None:
    store = InMemoryDataStore()
    graph_backend = _UnsupportedRedactionGraphBackend()
    service = SourceRedactionService(store, graph_backend=graph_backend, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001"))
            await tx.source_events.insert_if_absent(_source_event("source_002"))
            await tx.evidence_chunks.upsert_chunk(_evidence_chunk())
            await tx.memory_items.upsert(_memory_item("memory_primary", ("source_001",), "source_001"))
            await tx.memory_items.upsert(_memory_item("memory_supported", ("source_001", "source_002"), "source_002"))
            await tx.memory_pages.upsert(_page())
            await tx.push_candidates.upsert(_push_candidate())

        result = await service.purge_source(
            SourceRedactionCommand(
                source_event_id="source_001",
                scope=SCOPE,
                actor_id="user_001",
                reason="sensitive source content",
                idempotency_key="purge-source-001",
                trace_id="trace_redaction",
                purge_level="memwing_redaction",
            )
        )

        async with store.transaction() as tx:
            redacted = await tx.source_events.get_source_event("source_001")
            invalid = await tx.memory_items.get("memory_primary")
            review = await tx.memory_items.get("memory_supported")
            page = await tx.memory_pages.get("page_001")
            push = await tx.push_candidates.get("push_001")

        assert result.graph_backend_marker_attempted is True
        assert result.graph_backend_marker_succeeded is False
        assert result.graph_backend_warning == "unexpected_failure"
        assert graph_backend.source_event_ids == ("source_001",)
        assert redacted is not None
        assert redacted.content == REDACTED_SOURCE_CONTENT
        assert redacted.purge_level == "memwing_redaction"
        assert redacted.graph_backend_raw_retained is True
        assert invalid is not None
        assert invalid.status is MemoryStatus.INVALID
        assert review is not None
        assert review.status is MemoryStatus.NEEDS_REVIEW
        assert page is not None and page.needs_rebuild is True
        assert push is not None and push.status == "invalid"
        assert any(event.stage == "source_redaction.graph_backend.warning" for event in store.audit_events)

    asyncio.run(scenario())


class _UnsupportedRedactionGraphBackend:
    def __init__(self) -> None:
        self.source_event_ids: tuple[str, ...] = ()

    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        raise NotImplementedError

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request):
        raise NotImplementedError

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        self.source_event_ids = (*self.source_event_ids, source_event_id)
        raise NotImplementedError("Graphiti source redaction marker sync is not implemented")


def _source_event(source_event_id: str) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
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
        event_time=NOW - timedelta(days=1),
        raw_payload_hash=f"hash_{source_event_id}",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW - timedelta(days=1),
        runtime_event_idempotency_key=None,
    )


def _memory_item(memory_id: str, source_event_ids: tuple[str, ...], primary_source_event_id: str) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Demo scope",
        content="Demo scope remains Feishu plus OpenClaw.",
        summary="Demo scope remains stable.",
        source_event_ids=source_event_ids,
        primary_source_event_id=primary_source_event_id,
        status=MemoryStatus.ACTIVE,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
        original_score=0.8,
        half_life_days=10,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=NOW,
        activated_at=NOW,
        updated_at=NOW,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def _page() -> PageMemory:
    return PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Demo page",
        brief="Demo page brief.",
        topics=(PageMemoryTopic("Demo", "Summary", ("source_001",), ("memory_primary",)),),
        open_questions=(),
        next_steps=(),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_primary",),
        version=1,
        needs_rebuild=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _push_candidate() -> PushCandidate:
    return PushCandidate(
        id="push_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        type="forgetting_review",
        title="Review Demo scope",
        content="Demo scope needs review.",
        memory_item_ids=("memory_primary",),
        source_event_ids=("source_001",),
        trigger_reason="score_below_threshold",
        trigger_source="forgetting_review",
        priority=100,
        expires_at=None,
        status="pending",
        cooldown_key="forgetting_review:memory_primary",
        created_at=NOW,
        updated_at=NOW,
    )


def _evidence_chunk() -> EvidenceChunk:
    return EvidenceChunk(
        id="chunk_001",
        source_event_id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        chunk_text="Decision source text.",
        chunk_index=0,
        embedding_model=None,
        embedding_ref=None,
        embedding_vector=None,
        invalidated_at=None,
        created_at=NOW,
    )
