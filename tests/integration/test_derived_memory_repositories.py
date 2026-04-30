import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.core.models import (
    EvidenceChunk,
    GraphWriteJob,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryItem,
    MemoryPageVersion,
    MemoryRoute,
    MemoryStatus,
    MemoryVersion,
    PageMemory,
    PageMemoryTopic,
    SourceEvent,
    WorkingMemoryEntry,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore


NOW = datetime(2026, 4, 28, tzinfo=UTC)


def test_in_memory_derived_repositories_cover_lane_d_e_f_boundaries() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            source_event, inserted_source = await tx.source_events.insert_if_absent(
                _source_event()
            )
            later_source_event, inserted_later_source = await tx.source_events.insert_if_absent(
                replace(
                    _source_event(),
                    id="source_002",
                    raw_payload_hash="hash_002",
                    runtime_event_idempotency_key="runtime-key-002",
                    event_time=NOW + timedelta(minutes=5),
                    created_at=NOW + timedelta(minutes=5),
                )
            )
            chunk = await tx.evidence_chunks.upsert_chunk(_evidence_chunk())
            duplicated_chunk = await tx.evidence_chunks.upsert_chunk(
                replace(_evidence_chunk(), id="chunk_duplicate")
            )
            working_entry = await tx.working_memory_entries.append(_working_memory_entry())
            memory = await tx.memory_items.upsert(_memory_item())
            version = await tx.memory_versions.record(_memory_version())
            page = await tx.memory_pages.upsert(_page_memory())
            duplicated_page = await tx.memory_pages.upsert(
                replace(_page_memory(), id="page_duplicate", version=2)
            )
            page_version = await tx.memory_page_versions.record(_page_version())
            graph_job = await tx.graph_write_jobs.enqueue(_graph_job())
            graph_link = await tx.memory_graph_links.upsert(_graph_link())

        assert inserted_source is True
        assert inserted_later_source is True
        assert source_event.id == "source_001"
        assert chunk.id == "chunk_001"
        assert duplicated_chunk.id == "chunk_001"
        assert working_entry.source_event_id == "source_001"
        assert memory.status is MemoryStatus.CANDIDATE
        assert version.memory_id == memory.id
        assert page.version == 1
        assert duplicated_page.id == "page_001"
        assert duplicated_page.version == 2
        assert page_version.page_id == page.id
        assert graph_job.id == "graph_job_001"
        assert graph_link.memory_id == memory.id

        async with store.transaction() as tx:
            assert await tx.memory_items.get("memory_001") == memory
            assert await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            ) == duplicated_page
            assert await tx.memory_pages.get_by_scope_for_update(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            ) == duplicated_page
            assert await tx.evidence_chunks.mark_source_redacted(
                source_event_id="source_001",
                invalidated_at=NOW,
            ) == 1
            assert await tx.memory_pages.mark_needs_rebuild_for_source(
                source_event_id="source_001",
                updated_at=NOW,
            ) == 1
            assert await tx.memory_pages.list_needs_rebuild(
                project_memory_space_id="project_001",
                limit=10,
            ) == (replace(duplicated_page, needs_rebuild=True, updated_at=NOW),)
            assert await tx.memory_items.list_by_source_event("source_001") == (memory,)
            assert await tx.memory_items.list_for_scope(
                scope=_effective_scope(),
                limit=10,
            ) == (memory,)
            assert await tx.memory_versions.get_latest("memory_001") == version
            assert await tx.memory_graph_links.list_by_memory("memory_001") == (graph_link,)
            assert await tx.source_events.list_for_scope(
                scope=_effective_scope(),
                limit=10,
            ) == (source_event, later_source_event)
            assert await tx.source_events.list_recent_for_scope(
                scope=_effective_scope(),
                limit=1,
            ) == (later_source_event,)
            assert await tx.working_memory_entries.mark_flushed(
                project_memory_space_id="project_001",
                thread_id="thread_001",
                through_sequence=12,
                flushed_at=NOW,
            ) == 1
            assert await tx.working_memory_entries.next_sequence(
                project_memory_space_id="project_001",
                thread_id="thread_001",
            ) == 13
            assert await tx.working_memory_entries.sum_unflushed_tokens(
                project_memory_space_id="project_001",
                group_id="group_001",
                thread_id="thread_001",
            ) == 0
            claimed = await tx.graph_write_jobs.claim_pending(
                now=NOW,
                worker_id="graph_worker_001",
                lock_duration=timedelta(minutes=5),
                limit=1,
            )
            assert len(claimed) == 1
            assert claimed[0].locked_by == "graph_worker_001"
            await tx.graph_write_jobs.mark_succeeded(
                job_id=claimed[0].id,
                locked_by="graph_worker_001",
                now=NOW,
            )

    asyncio.run(scenario())


def _source_event() -> SourceEvent:
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


def _working_memory_entry() -> WorkingMemoryEntry:
    return WorkingMemoryEntry(
        id="working_001",
        source_event_id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        content="Recent message.",
        token_count=4,
        sequence=12,
        flushed_at=None,
        created_at=NOW,
    )


def _memory_item() -> MemoryItem:
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


def _memory_version() -> MemoryVersion:
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
        created_at=NOW,
    )


def _page_memory() -> PageMemory:
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
        topics=(_page_topic(),),
        open_questions=("Which lane owns recall warnings?",),
        next_steps=("Wire the page memory worker.",),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
        version=1,
        needs_rebuild=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _page_version() -> MemoryPageVersion:
    return MemoryPageVersion(
        id="page_version_001",
        page_id="page_001",
        version=1,
        title="Thread mainline",
        brief="The thread is validating memory lanes.",
        topics=(_page_topic(),),
        open_questions=("Which lane owns recall warnings?",),
        next_steps=("Wire the page memory worker.",),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
        changed_by="system",
        change_reason="initial_rebuild",
        created_at=NOW,
    )


def _page_topic() -> PageMemoryTopic:
    return PageMemoryTopic(
        title="Memory lane validation",
        summary="The thread is validating derived memory lanes.",
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
    )


def _effective_scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )


def _graph_job() -> GraphWriteJob:
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
        next_run_at=NOW,
        dead_letter_reason=None,
        last_error=None,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _graph_link() -> MemoryGraphLink:
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
        created_at=NOW,
    )
