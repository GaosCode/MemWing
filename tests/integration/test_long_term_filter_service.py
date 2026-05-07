from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from memwing.application.long_term_filter_service import (
    LongTermFilterProcessCommand,
    LongTermFilterService,
)
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.models import (
    LongTermFilterItem,
    MemoryDisplayType,
    MemoryRoute,
    MemoryStatus,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.llm_filter import LongTermFilterRequest


NOW = datetime(2026, 4, 30, tzinfo=UTC)


def test_long_term_filter_service_auto_activates_recallable_items_and_enqueues_graph_routes() -> None:
    async def scenario() -> None:
        store = InMemoryDataStore()
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001", "Graph fact"))
            await tx.source_events.insert_if_absent(_source_event("source_002", "Vector note"))

        filter_port = _FakeLongTermFilterPort(
            (
                _filter_item(
                    title="Graph memory",
                    route=MemoryRoute.GRAPH,
                    source_event_ids=("source_001",),
                    display_type=MemoryDisplayType.DECISION,
                ),
                _filter_item(
                    title="Vector memory",
                    route=MemoryRoute.VECTOR_ONLY,
                    source_event_ids=("source_002",),
                ),
            )
        )
        service = LongTermFilterService(
            store,
            filter_port,
            lifecycle_transition=LifecycleTransitionService(store),
        )

        result = await service.process_scope(
            LongTermFilterProcessCommand(
                scope=_scope(),
                source_event_ids=("source_001", "source_002"),
                now=NOW,
                trace_id="trace_001",
            )
        )

        assert result.source_event_count == 2
        assert result.candidate_count == 2
        assert result.activated_count == 2
        assert result.graph_write_job_count == 1
        assert result.push_candidate_count == 1
        assert filter_port.last_request is not None
        assert {event.id for event in filter_port.last_request.source_events} == {
            "source_001",
            "source_002",
        }

        async with store.transaction() as tx:
            items = await tx.memory_items.list_for_scope(scope=_scope(), limit=10)

        assert {item.title for item in items} == {"Graph memory", "Vector memory"}
        assert {item.status for item in items} == {MemoryStatus.ACTIVE}
        assert all(item.activated_at == NOW for item in items)
        assert len(store.graph_write_jobs) == 1
        assert store.graph_write_jobs[0].memory_id in {item.id for item in items}
        assert len(store.push_candidates) == 1
        assert store.push_candidates[0].type == "decision_card"
        assert store.audit_events[-1].stage == "long_term_filter.succeeded"

    asyncio.run(scenario())


def test_long_term_filter_service_rejects_filter_output_for_unloaded_source_events() -> None:
    async def scenario() -> None:
        store = InMemoryDataStore()
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001", "Loaded"))

        service = LongTermFilterService(
            store,
            _FakeLongTermFilterPort(
                (
                    _filter_item(
                        title="Bad source",
                        route=MemoryRoute.VECTOR_ONLY,
                        source_event_ids=("source_missing",),
                    ),
                )
            ),
            lifecycle_transition=LifecycleTransitionService(store),
        )

        with pytest.raises(ValueError, match="source_event_ids outside"):
            await service.process_scope(
                LongTermFilterProcessCommand(
                    scope=_scope(),
                    source_event_ids=("source_001",),
                    now=NOW,
                    trace_id="trace_bad",
                )
            )

        async with store.transaction() as tx:
            assert await tx.memory_items.list_for_scope(scope=_scope(), limit=10) == ()

    asyncio.run(scenario())


def test_long_term_filter_service_keeps_manual_and_raw_items_as_candidates() -> None:
    async def scenario() -> None:
        store = InMemoryDataStore()
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001", "Manual review"))
            await tx.source_events.insert_if_absent(_source_event("source_002", "Raw note"))

        service = LongTermFilterService(
            store,
            _FakeLongTermFilterPort(
                (
                    _filter_item(
                        title="Manual memory",
                        route=MemoryRoute.MANUAL,
                        source_event_ids=("source_001",),
                    ),
                    _filter_item(
                        title="Raw memory",
                        route=MemoryRoute.RAW_ONLY,
                        source_event_ids=("source_002",),
                    ),
                )
            ),
            lifecycle_transition=LifecycleTransitionService(store),
        )

        result = await service.process_scope(
            LongTermFilterProcessCommand(
                scope=_scope(),
                source_event_ids=("source_001", "source_002"),
                now=NOW,
                trace_id="trace_manual",
            )
        )

        assert result.candidate_count == 2
        assert result.activated_count == 0
        async with store.transaction() as tx:
            items = await tx.memory_items.list_for_scope(scope=_scope(), limit=10)

        assert {item.status for item in items} == {MemoryStatus.CANDIDATE}

    asyncio.run(scenario())


def test_long_term_filter_service_retry_does_not_demote_active_memory() -> None:
    async def scenario() -> None:
        store = InMemoryDataStore()
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event("source_001", "Graph fact"))

        service = LongTermFilterService(
            store,
            _FakeLongTermFilterPort(
                (
                    _filter_item(
                        title="Graph memory",
                        route=MemoryRoute.GRAPH,
                        source_event_ids=("source_001",),
                    ),
                )
            ),
            lifecycle_transition=LifecycleTransitionService(store),
        )

        first = await service.process_scope(
            LongTermFilterProcessCommand(
                scope=_scope(),
                source_event_ids=("source_001",),
                now=NOW,
                trace_id="trace_retry",
            )
        )
        second = await service.process_scope(
            LongTermFilterProcessCommand(
                scope=_scope(),
                source_event_ids=("source_001",),
                now=NOW,
                trace_id="trace_retry",
            )
        )

        assert first.activated_count == 1
        assert second.activated_count == 0
        async with store.transaction() as tx:
            items = await tx.memory_items.list_for_scope(scope=_scope(), limit=10)

        assert len(items) == 1
        assert items[0].status is MemoryStatus.ACTIVE
        assert items[0].lifecycle_revision == 1

    asyncio.run(scenario())


class _FakeLongTermFilterPort:
    def __init__(self, items: tuple[LongTermFilterItem, ...]) -> None:
        self._items = items
        self.last_request: LongTermFilterRequest | None = None

    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        self.last_request = request
        return self._items


def _scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )


def _source_event(source_event_id: str, content: str) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="agent_runtime.message_ingested",
        content=content,
        content_preview=content,
        source_url=None,
        event_time=NOW,
        raw_payload_hash=f"hash:{source_event_id}",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
        runtime_event_idempotency_key=f"runtime:{source_event_id}",
    )


def _filter_item(
    *,
    title: str,
    route: MemoryRoute,
    source_event_ids: tuple[str, ...],
    display_type: MemoryDisplayType = MemoryDisplayType.NOTE,
) -> LongTermFilterItem:
    return LongTermFilterItem(
        title=title,
        content=f"{title} content",
        route=route,
        display_type=display_type,
        original_score=0.82,
        half_life_days=30,
        source_event_ids=source_event_ids,
        primary_source_event_id=source_event_ids[0],
        reason="stable enough for long-term memory",
        confidence=0.9,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
    )
