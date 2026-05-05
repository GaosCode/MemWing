import asyncio
from datetime import UTC, datetime

from memwing.application.source_redaction_service import (
    SourceRedactionCommand,
    SourceRedactionService,
)
from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.model_result_cache import ModelResultCacheEntry, ModelResultCacheKey


NOW = datetime(2026, 5, 5, tzinfo=UTC)


def test_source_redaction_invalidates_model_result_cache_by_lineage() -> None:
    store = InMemoryDataStore()
    service = SourceRedactionService(store, now=lambda: NOW)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event())
            await tx.model_result_cache.put(
                ModelResultCacheEntry(
                    id="cache_001",
                    key=_cache_key(project_memory_space_id="project_001"),
                    source_event_ids=("source_001",),
                    value_json={"vector_size": 2},
                    embedding_vector=(0.1, 0.2),
                    status="active",
                    created_at=NOW,
                    last_hit_at=None,
                    hit_count=0,
                    invalidated_at=None,
                    invalidated_reason=None,
                    expires_at=None,
                )
            )
            await tx.model_result_cache.put(
                ModelResultCacheEntry(
                    id="cache_other_project",
                    key=_cache_key(project_memory_space_id="project_002"),
                    source_event_ids=("source_001",),
                    value_json={"vector_size": 2},
                    embedding_vector=(0.3, 0.4),
                    status="active",
                    created_at=NOW,
                    last_hit_at=None,
                    hit_count=0,
                    invalidated_at=None,
                    invalidated_reason=None,
                    expires_at=None,
                )
            )

        await service.purge_source(
            SourceRedactionCommand(
                source_event_id="source_001",
                scope=_scope(),
                actor_id="admin_001",
                reason="user requested source redaction",
                idempotency_key="redact:source_001",
                trace_id="trace_001",
                purge_level="memwing_redaction",
            )
        )

        async with store.transaction() as tx:
            project_entries = await tx.model_result_cache.list_by_source_event(
                project_memory_space_id="project_001",
                source_event_id="source_001",
            )
            other_entries = await tx.model_result_cache.list_by_source_event(
                project_memory_space_id="project_002",
                source_event_id="source_001",
            )

        assert project_entries[0].status == "invalidated"
        assert project_entries[0].invalidated_at == NOW
        assert project_entries[0].invalidated_reason == "source_redaction"
        assert other_entries[0].status == "active"

    asyncio.run(scenario())


def _cache_key(*, project_memory_space_id: str) -> ModelResultCacheKey:
    return ModelResultCacheKey(
        project_memory_space_id=project_memory_space_id,
        cache_kind="embedding",
        role="evidence_embedding",
        runtime="openclaw",
        model="embedding-model",
        transport="local",
        prompt_hash="none",
        input_hash="input_hash",
        schema_hash="embedding:v1",
    )


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
        content="Ada owns the roadmap.",
        content_preview="Ada owns the roadmap.",
        source_url=None,
        event_time=NOW,
        raw_payload_hash="hash_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
        runtime_event_idempotency_key="runtime-key-001",
    )


def _scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=False,
        cross_group_allowed=True,
    )
