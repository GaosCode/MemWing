from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memwing.application.pipeline_readiness_service import PipelineReadinessService
from memwing.application.remember_event_records import outbox_job
from memwing.core.models import (
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    PageMemory,
    PageMemoryTopic,
    SourceEvent,
)
from memwing.core.pipeline_readiness import PipelineReadinessCommand, PipelineReadinessProfile
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore


NOW = datetime(2026, 5, 3, tzinfo=UTC)


def test_minimal_ingest_ready_after_source_events_exist() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        source = _source_event("source_001")
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source)

        result = await PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
        ).check(
            PipelineReadinessCommand(
                source_event_ids=("source_001",),
                scope=_scope(),
                profile=PipelineReadinessProfile.MINIMAL_INGEST,
            )
        )

        assert result.ready is True
        assert result.source_events.available == 1

    asyncio.run(run())


def test_write_evaluate_requires_page_memory_and_memory_items() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        source = _source_event("source_001")
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source)
            for job_type in (
                "page_memory.maybe_rebuild",
                "long_term_filter.classify",
            ):
                await tx.outbox_jobs.enqueue(
                    replace(outbox_job(source_event=source, job_type=job_type, now=NOW), status="succeeded")
                )
            await tx.memory_pages.upsert(_page())
            await tx.memory_items.upsert(_memory_item())

        result = await PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
        ).check(
            PipelineReadinessCommand(
                source_event_ids=("source_001",),
                scope=_scope(),
                profile=PipelineReadinessProfile.WRITE_EVALUATE,
            )
        )

        assert result.ready is True
        assert result.derived["page_memory"].ready is True
        assert result.derived["page_memory"].matched_source_event_ids == ("source_001",)
        assert result.derived["page_memory"].unmatched_source_event_ids == ()
        assert result.derived["page_memory"].page_ids == ("page_001",)
        assert result.derived["memory_items"].ready is True

    asyncio.run(run())


def test_write_evaluate_counts_only_current_active_memory_items() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        source = _source_event("source_001")
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source)
            for job_type in (
                "page_memory.maybe_rebuild",
                "long_term_filter.classify",
            ):
                await tx.outbox_jobs.enqueue(
                    replace(outbox_job(source_event=source, job_type=job_type, now=NOW), status="succeeded")
                )
            await tx.memory_pages.upsert(_page())
            await tx.memory_items.upsert(
                replace(_memory_item(), status=MemoryStatus.CANDIDATE, activated_at=None)
            )

        result = await PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
        ).check(
            PipelineReadinessCommand(
                source_event_ids=("source_001",),
                scope=_scope(),
                profile=PipelineReadinessProfile.WRITE_EVALUATE,
            )
        )

        assert result.ready is False
        assert result.derived["memory_items"].ready is False
        assert result.derived["memory_items"].count == 0
        assert result.derived["memory_items"].reason == "memory_items_empty"

    asyncio.run(run())


def test_write_evaluate_page_memory_requires_current_source_reference() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        source = _source_event("source_001")
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source)
            for job_type in (
                "page_memory.maybe_rebuild",
                "long_term_filter.classify",
            ):
                await tx.outbox_jobs.enqueue(
                    replace(outbox_job(source_event=source, job_type=job_type, now=NOW), status="succeeded")
                )
            await tx.memory_pages.upsert(_page(source_event_ids=("old_source",)))
            await tx.memory_items.upsert(_memory_item())

        result = await PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
        ).check(
            PipelineReadinessCommand(
                source_event_ids=("source_001",),
                scope=_scope(),
                profile=PipelineReadinessProfile.WRITE_EVALUATE,
            )
        )

        assert result.ready is False
        assert result.derived["page_memory"].ready is False
        assert result.derived["page_memory"].count == 0
        assert result.derived["page_memory"].reason == "page_memory_empty"
        assert result.derived["page_memory"].matched_source_event_ids == ()
        assert result.derived["page_memory"].unmatched_source_event_ids == ("source_001",)
        assert result.derived["page_memory"].page_ids == ()

    asyncio.run(run())


def test_write_evaluate_ignores_page_memory_that_still_needs_rebuild() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        source = _source_event("source_001")
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source)
            for job_type in (
                "page_memory.maybe_rebuild",
                "long_term_filter.classify",
            ):
                await tx.outbox_jobs.enqueue(
                    replace(outbox_job(source_event=source, job_type=job_type, now=NOW), status="succeeded")
                )
            await tx.memory_pages.upsert(_page(needs_rebuild=True))
            await tx.memory_items.upsert(_memory_item())

        result = await PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
        ).check(
            PipelineReadinessCommand(
                source_event_ids=("source_001",),
                scope=_scope(),
                profile=PipelineReadinessProfile.WRITE_EVALUATE,
            )
        )

        assert result.ready is False
        assert result.derived["page_memory"].ready is False
        assert result.derived["page_memory"].unmatched_source_event_ids == ("source_001",)

    asyncio.run(run())


def test_required_dead_letter_blocks_write_evaluate() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        source = _source_event("source_001")
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source)
            await tx.outbox_jobs.enqueue(
                replace(
                    outbox_job(source_event=source, job_type="long_term_filter.classify", now=NOW),
                    status="dead_letter",
                    dead_letter_reason="ProviderPermanentFailure",
                )
            )
            await tx.outbox_jobs.enqueue(
                replace(outbox_job(source_event=source, job_type="page_memory.maybe_rebuild", now=NOW), status="succeeded")
            )
            await tx.memory_pages.upsert(_page())

        result = await PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
        ).check(
            PipelineReadinessCommand(
                source_event_ids=("source_001",),
                scope=_scope(),
                profile=PipelineReadinessProfile.WRITE_EVALUATE,
            )
        )

        assert result.ready is False
        assert result.derived["memory_items"].reason == "dead_letter"
        assert "long_term_filter.classify:dead_letter" in result.warnings

    asyncio.run(run())


def test_processing_lock_is_classified_as_stale() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        source = _source_event("source_001")
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source)
            await tx.outbox_jobs.enqueue(
                replace(
                    outbox_job(source_event=source, job_type="working_memory.append", now=NOW),
                    status="processing",
                    locked_at=NOW - timedelta(minutes=10),
                    locked_by="worker_001",
                    lock_expires_at=NOW - timedelta(minutes=5),
                )
            )

        result = await PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
        ).check(
            PipelineReadinessCommand(
                source_event_ids=("source_001",),
                scope=_scope(),
                profile=PipelineReadinessProfile.CONTEXT_ASSEMBLE,
            ),
            now=NOW,
        )

        assert result.ready is False
        assert result.outbox.processing_stale == 1
        assert result.derived["working_memory"].reason == "processing_stale"

    asyncio.run(run())


def _source_event(source_event_id: str) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id=None,
        author_name=None,
        source_type="text",
        content=f"Content for {source_event_id}",
        content_preview=f"Content for {source_event_id}",
        source_url=None,
        event_time=NOW,
        raw_payload_hash=f"hash_{source_event_id}",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
    )


def _scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )


def _page(
    *,
    source_event_ids: tuple[str, ...] = ("source_001",),
    needs_rebuild: bool = False,
) -> PageMemory:
    return PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Page",
        brief="Page brief",
        topics=(
            PageMemoryTopic(
                title="Topic",
                summary="Summary",
                source_event_ids=source_event_ids[:1],
                linked_memory_item_ids=(),
            ),
        ),
        open_questions=(),
        next_steps=(),
        source_event_ids=source_event_ids,
        linked_memory_item_ids=(),
        version=1,
        needs_rebuild=needs_rebuild,
        created_at=NOW,
        updated_at=NOW,
    )


def _memory_item() -> MemoryItem:
    return MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.VECTOR_ONLY,
        display_type=MemoryDisplayType.NOTE,
        title="Memory",
        content="Memory content",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.ACTIVE,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
        original_score=1.0,
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
        activated_at=NOW,
        updated_at=NOW,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )
