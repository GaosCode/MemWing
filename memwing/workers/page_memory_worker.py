from __future__ import annotations

from dataclasses import dataclass

from memwing.application.page_memory_service import (
    PageMemoryRebuildCommand,
    PageMemoryService,
)
from memwing.core.models import OutboxJob, PageMemory
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import EventStoreUnitOfWorkPort


PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE = "page_memory.maybe_rebuild"


@dataclass(frozen=True, slots=True)
class PageMemoryWorkerResult:
    scanned: int
    rebuilt: int


class PageMemoryWorker:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        page_memory_service: PageMemoryService,
        *,
        rebuild_limit: int = 10,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._page_memory_service = page_memory_service
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
            await self._page_memory_service.rebuild(
                PageMemoryRebuildCommand(
                    scope=_effective_scope_from_page(page),
                    scope_type=page.scope_type,
                    scope_id=page.scope_id,
                    actor_id=None,
                    reason="needs_rebuild",
                    trace_id=f"page_memory:{job.id}:{page.id}",
                )
            )
            rebuilt += 1

        return PageMemoryWorkerResult(scanned=len(candidates), rebuilt=rebuilt)


def _effective_scope_from_page(page: PageMemory) -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id=page.project_memory_space_id,
        group_ids=(page.group_id,) if page.group_id is not None else None,
        thread_id=page.thread_id,
        shared_group_id=page.shared_group_id,
        safe_mode_enabled=page.group_id is not None,
        cross_group_allowed=page.group_id is None,
    )
