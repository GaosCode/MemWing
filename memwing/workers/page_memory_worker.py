from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from memwing.application.page_memory_policy import (
    PageMemoryPolicy,
    PageMemoryPolicyDecision,
    PageMemoryPolicyInput,
)
from memwing.application.page_memory_rebuild import (
    DEFAULT_PAGE_MEMORY_SOURCE_EVENT_LIMIT,
    NEEDS_REBUILD_REASON,
    SOURCE_EVENT_TRIGGER_REASON,
)
from memwing.application.page_memory_service import (
    PageMemoryRebuildCommand,
    PageMemoryRebuildResult,
    PageMemoryService,
)
from memwing.application.page_memory_trigger import page_memory_target_from_source_event
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
        policy: PageMemoryPolicy | None = None,
        rebuild_limit: int = 10,
        source_event_limit: int = DEFAULT_PAGE_MEMORY_SOURCE_EVENT_LIMIT,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._page_memory_service = page_memory_service
        self._scope_resolver = scope_resolver
        self._policy = policy or PageMemoryPolicy()
        self._rebuild_limit = rebuild_limit
        self._source_event_limit = source_event_limit

    async def maybe_rebuild(self, job: OutboxJob) -> PageMemoryWorkerResult:
        if job.job_type != PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE:
            raise ValueError("page memory worker received unsupported outbox job type")

        async with self._unit_of_work.transaction() as tx:
            source_event = await tx.source_events.get_source_event(job.source_event_id)
        if source_event is None:
            raise RuntimeError("page memory trigger source event was not found")
        if source_event.project_memory_space_id != job.project_memory_space_id:
            raise RuntimeError("page memory trigger source event project does not match job")

        target = page_memory_target_from_source_event(source_event)
        async with self._unit_of_work.transaction() as tx:
            existing_page = await tx.memory_pages.get_by_scope(
                project_memory_space_id=target.scope.project_memory_space_id,
                scope_type=target.scope_type,
                scope_id=target.scope_id,
            )
            source_events = await tx.source_events.list_recent_for_scope(
                scope=target.scope,
                limit=self._source_event_limit,
            )

        policy_result = self._policy.evaluate(
            PageMemoryPolicyInput(
                existing_page=existing_page,
                source_events=source_events,
            )
        )
        if policy_result.decision == PageMemoryPolicyDecision.SKIP:
            return PageMemoryWorkerResult(scanned=1, rebuilt=0)

        rebuild_result = await self._page_memory_service.rebuild(
            PageMemoryRebuildCommand(
                scope=target.scope,
                scope_type=target.scope_type,
                scope_id=target.scope_id,
                actor_id=None,
                reason=_rebuild_reason(existing_page),
                trace_id=f"page_memory:{job.id}:{target.scope_type}:{target.scope_id}",
            )
        )
        return PageMemoryWorkerResult(
            scanned=1,
            rebuilt=1 if isinstance(rebuild_result, PageMemoryRebuildResult) else 0,
        )


def _rebuild_reason(existing_page: PageMemory | None) -> str:
    if existing_page is not None and existing_page.needs_rebuild:
        return NEEDS_REBUILD_REASON
    return SOURCE_EVENT_TRIGGER_REASON
