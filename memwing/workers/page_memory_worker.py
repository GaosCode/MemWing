from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from memwing.application.page_memory_service import (
    PageMemoryRebuildCommand,
    PageMemoryRebuildResult,
    PageMemoryService,
)
from memwing.application.scope_resolver import ResolvedScope
from memwing.core.models import OutboxJob, PageMemory
from memwing.ports.event_store import EventStoreUnitOfWorkPort


PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE = "page_memory.maybe_rebuild"


@dataclass(frozen=True, slots=True)
class PageMemoryWorkerResult:
    scanned: int
    rebuilt: int


class PageMemoryRebuildScopeResolver(Protocol):
    async def resolve_page_memory_rebuild(self, page: PageMemory) -> ResolvedScope:
        ...


class PageMemoryWorker:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        page_memory_service: PageMemoryService,
        *,
        scope_resolver: PageMemoryRebuildScopeResolver,
        rebuild_limit: int = 10,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._page_memory_service = page_memory_service
        self._scope_resolver = scope_resolver
        self._rebuild_limit = rebuild_limit

    async def maybe_rebuild(self, job: OutboxJob) -> PageMemoryWorkerResult:
        if job.job_type != PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE:
            raise ValueError("page memory worker received unsupported outbox job type")

        async with self._unit_of_work.transaction() as tx:
            candidates = await tx.memory_pages.list_needs_rebuild(
                project_memory_space_id=job.project_memory_space_id,
                limit=self._rebuild_limit,
            )

        rebuilt = 0
        for page in candidates:
            resolved_scope = await self._scope_resolver.resolve_page_memory_rebuild(page)
            rebuild_result = await self._page_memory_service.rebuild(
                PageMemoryRebuildCommand(
                    scope=resolved_scope.effective_scope,
                    scope_type=page.scope_type,
                    scope_id=page.scope_id,
                    actor_id=None,
                    reason="needs_rebuild",
                    trace_id=f"page_memory:{job.id}:{page.id}",
                )
            )
            if isinstance(rebuild_result, PageMemoryRebuildResult):
                rebuilt += 1

        return PageMemoryWorkerResult(scanned=len(candidates), rebuilt=rebuilt)
