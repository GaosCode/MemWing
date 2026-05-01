from __future__ import annotations

from datetime import UTC, datetime

from memwing.application.page_memory_rebuild import (
    DEFAULT_PAGE_MEMORY_LINKED_ITEM_LIMIT,
    DEFAULT_PAGE_MEMORY_SOURCE_EVENT_LIMIT,
    NEEDS_REBUILD_REASON,
    PageMemoryCommit,
    PageMemoryRebuildCommand,
    PageMemoryRebuildError as PageMemoryRebuildError,
    PageMemoryRebuildNoOp,
    PageMemoryRebuildPlanner,
    PageMemoryRebuildPreview,
    PageMemoryRebuildResult,
    PageMemorySynthesisGuard,
    PageMemorySynthesisValidationError as PageMemorySynthesisValidationError,
    current_source_window_changed,
)
from memwing.ports.clock import ClockPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.page_memory_synthesis import PageMemorySynthesisPort


class PageMemoryService:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        synthesis: PageMemorySynthesisPort,
        *,
        clock: ClockPort | None = None,
        source_event_limit: int = DEFAULT_PAGE_MEMORY_SOURCE_EVENT_LIMIT,
        linked_item_limit: int = DEFAULT_PAGE_MEMORY_LINKED_ITEM_LIMIT,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._synthesis = synthesis
        self._clock = clock or _SystemClock()
        self._source_event_limit = source_event_limit
        self._linked_item_limit = linked_item_limit
        self._planner = PageMemoryRebuildPlanner(
            source_event_limit=source_event_limit,
            linked_item_limit=linked_item_limit,
        )
        self._guard = PageMemorySynthesisGuard()
        self._commit = PageMemoryCommit()

    async def rebuild(
        self,
        command: PageMemoryRebuildCommand,
    ) -> PageMemoryRebuildResult | PageMemoryRebuildNoOp:
        async with self._unit_of_work.transaction() as tx:
            plan = await self._planner.plan(tx, command)

        synthesis = await self._synthesis.synthesize(
            plan.synthesis_request()
        )
        guarded = self._guard.validate(plan=plan, synthesis=synthesis)

        async with self._unit_of_work.transaction() as tx:
            await tx.memory_pages.lock_scope(
                project_memory_space_id=command.scope.project_memory_space_id,
                scope_type=command.scope_type,
                scope_id=command.scope_id,
            )
            current_page = await tx.memory_pages.get_by_scope_for_update(
                project_memory_space_id=command.scope.project_memory_space_id,
                scope_type=command.scope_type,
                scope_id=command.scope_id,
            )
            if command.reason == NEEDS_REBUILD_REASON and current_page is not None:
                if not current_page.needs_rebuild:
                    return PageMemoryRebuildNoOp(
                        page=current_page,
                        reason="already_rebuilt",
                    )
                current_source_events = await tx.source_events.list_recent_for_scope(
                    scope=command.scope,
                    limit=self._source_event_limit,
                )
                if current_source_window_changed(current_source_events, plan):
                    return PageMemoryRebuildNoOp(
                        page=current_page,
                        reason="source_window_changed",
                    )
            now = self._clock.now()
            return await self._commit.commit(
                tx,
                command=command,
                current_page=current_page,
                guarded=guarded,
                now=now,
            )

    async def preview_rebuild(self, command: PageMemoryRebuildCommand) -> PageMemoryRebuildPreview:
        async with self._unit_of_work.transaction() as tx:
            plan = await self._planner.plan(tx, command)
        synthesis = await self._synthesis.synthesize(plan.synthesis_request())
        guarded = self._guard.validate(plan=plan, synthesis=synthesis)
        return guarded.preview()


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
