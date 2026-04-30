import asyncio
from datetime import UTC, datetime

from memwing.application.page_memory_service import PageMemoryRebuildCommand, PageMemoryService
from memwing.core.models import (
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    PageMemorySynthesis,
    PageMemoryTopic,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest


NOW = datetime(2026, 4, 28, 12, tzinfo=UTC)


def test_rebuild_only_passes_current_memory_items_to_synthesis() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event("source_current", "Only current memory items may inform Page Memory."),
    )
    _seed_memory_items(
        store,
        _memory_item("memory_active", status=MemoryStatus.ACTIVE),
        _memory_item("memory_pinned", status=MemoryStatus.FADING, pinned=True),
        _memory_item("memory_candidate", status=MemoryStatus.CANDIDATE),
        _memory_item("memory_hidden", status=MemoryStatus.HIDDEN),
        _memory_item("memory_invalid", status=MemoryStatus.INVALID),
        _memory_item("memory_removed", status=MemoryStatus.REMOVED),
    )
    synthesis = _EchoLinkedMemorySynthesis()
    service = PageMemoryService(store, synthesis, clock=_FixedClock(NOW))

    result = asyncio.run(
        service.rebuild(
            PageMemoryRebuildCommand(
                scope=_effective_scope(),
                scope_type="thread",
                scope_id="thread_001",
                actor_id="user_001",
                reason="manual_rebuild",
                trace_id="trace_current_memory_links",
            )
        )
    )

    linked_ids = {item.id for item in synthesis.requests[0].linked_memory_items}
    assert linked_ids == {"memory_active", "memory_pinned"}
    assert set(result.page.linked_memory_item_ids) == {"memory_active", "memory_pinned"}


def _seed_source_events(
    store: InMemoryDataStore,
    *events: SourceEvent,
) -> InMemoryDataStore:
    async def seed() -> None:
        async with store.transaction() as tx:
            for event in events:
                await tx.source_events.insert_if_absent(event)

    asyncio.run(seed())
    return store


def _seed_memory_items(
    store: InMemoryDataStore,
    *items: MemoryItem,
) -> InMemoryDataStore:
    async def seed() -> None:
        async with store.transaction() as tx:
            for item in items:
                await tx.memory_items.upsert(item)

    asyncio.run(seed())
    return store


def _source_event(source_event_id: str, content: str) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content=content,
        content_preview=content,
        source_url=None,
        event_time=NOW,
        raw_payload_hash=f"hash_{source_event_id}",
        metadata={"message_id": source_event_id},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
        runtime_event_idempotency_key=f"runtime_{source_event_id}",
    )


def _memory_item(
    memory_id: str,
    *,
    status: MemoryStatus,
    pinned: bool = False,
) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title=f"Memory {memory_id}",
        content=f"Linked memory {memory_id}.",
        summary=None,
        source_event_ids=("source_current",),
        primary_source_event_id="source_current",
        status=status,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
        original_score=0.8,
        half_life_days=30,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=pinned,
        created_by="system",
        created_at=NOW,
        activated_at=NOW if status is MemoryStatus.ACTIVE else None,
        updated_at=NOW,
        archived_at=None,
        hidden_at=NOW if status is MemoryStatus.HIDDEN else None,
        invalidated_at=NOW if status is MemoryStatus.INVALID else None,
        removed_at=NOW if status is MemoryStatus.REMOVED else None,
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


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _EchoLinkedMemorySynthesis:
    def __init__(self) -> None:
        self.requests: list[PageMemorySynthesisRequest] = []

    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        self.requests.append(request)
        source_event_ids = tuple(event.id for event in request.source_events)
        linked_memory_item_ids = tuple(item.id for item in request.linked_memory_items)
        return PageMemorySynthesis(
            title="Current memory links",
            brief="Only current facts are linked into Page Memory.",
            topics=(
                PageMemoryTopic(
                    title="Current facts",
                    summary="Synthesis receives active or pinned memory items only.",
                    source_event_ids=source_event_ids,
                    linked_memory_item_ids=linked_memory_item_ids,
                ),
            ),
            open_questions=(),
            next_steps=(),
            source_event_ids=source_event_ids,
            linked_memory_item_ids=linked_memory_item_ids,
        )
