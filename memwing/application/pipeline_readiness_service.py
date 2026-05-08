from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import uuid

from memwing.application.pipeline_readiness_jobs import job_count, outbox_readiness
from memwing.application.outbox_job_catalog import (
    EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,
    LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
    PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
    aggregate_key_for_scope_job,
)
from memwing.application.pipeline_readiness_status import (
    build_derived_readiness,
    profile_terminally_blocked,
    profile_ready,
    warnings_for_readiness,
)
from memwing.application.memory_item_ranking import is_current_recallable_memory_item
from memwing.core.models import MemoryItem, OutboxJob, PageMemory, SourceEvent
from memwing.core.pipeline_readiness import (
    JobStatusCount,
    PipelineReadinessCommand,
    PipelineReadinessResult,
    SourceEventReadiness,
)
from memwing.core.scope import EffectiveScope
from memwing.core.scope_visibility import (
    memory_item_visible_in_scope,
    source_event_visible_in_scope,
)
from memwing.ports.event_store import EventStoreUnitOfWorkPort


class PipelineReadinessService:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        evidence_enabled: bool,
        graph_enabled: bool,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._evidence_enabled = evidence_enabled
        self._graph_enabled = graph_enabled
        self._poll_interval_seconds = poll_interval_seconds

    async def check(
        self,
        command: PipelineReadinessCommand,
        *,
        now: datetime | None = None,
    ) -> PipelineReadinessResult:
        checked_at = now or datetime.now(UTC)
        async with self._unit_of_work.transaction() as tx:
            source_events = await _load_available_source_events(
                tx.source_events,
                command.source_event_ids,
                command.scope,
            )
            source_readiness = SourceEventReadiness(
                expected=len(command.source_event_ids),
                available=len(source_events),
                missing_source_event_ids=tuple(
                    source_event_id
                    for source_event_id in command.source_event_ids
                    if source_event_id not in source_events
                ),
            )

            outbox_jobs = await _related_outbox_jobs(
                tx.outbox_jobs,
                source_events.values(),
                scope=command.scope,
            )
            outbox_status = outbox_readiness(outbox_jobs, now=checked_at)
            outbox_by_type = outbox_status.by_job_type

            evidence_count = (
                await tx.evidence_chunks.count_by_source_events(
                    project_memory_space_id=command.scope.project_memory_space_id,
                    source_event_ids=tuple(source_events),
                )
                if self._evidence_enabled and source_events
                else 0
            )
            working_count = (
                await tx.working_memory_entries.count_by_source_events(
                    project_memory_space_id=command.scope.project_memory_space_id,
                    source_event_ids=tuple(source_events),
                )
                if source_events
                else 0
            )
            page_coverage = _page_memory_coverage(
                await tx.memory_pages.list_for_scope(scope=command.scope, limit=20),
                source_event_ids=tuple(source_events),
            )
            memory_items = await _memory_items_for_source_events(
                tx.memory_items,
                source_event_ids=tuple(source_events),
                scope=command.scope,
            )
            graph_jobs = (
                await tx.graph_write_jobs.list_for_source_events(
                    project_memory_space_id=command.scope.project_memory_space_id,
                    source_event_ids=tuple(source_events),
                )
                if self._graph_enabled and source_events
                else ()
            )

        graph_status = job_count(graph_jobs, now=checked_at)
        evidence_status = outbox_by_type.get(EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE)
        indexed_evidence_count = _indexed_evidence_count(
            stored_count=evidence_count,
            source_event_count=source_readiness.available,
            evidence_status=evidence_status,
        )
        derived = build_derived_readiness(
            source_readiness=source_readiness,
            outbox_by_type=outbox_by_type,
            evidence_enabled=self._evidence_enabled,
            graph_enabled=self._graph_enabled,
            evidence_count=indexed_evidence_count,
            working_count=working_count,
            page_count=len(page_coverage.pages),
            page_ids=tuple(page.id for page in page_coverage.pages),
            page_matched_source_event_ids=page_coverage.matched_source_event_ids,
            page_unmatched_source_event_ids=page_coverage.unmatched_source_event_ids,
            memory_item_count=len(memory_items),
            graph_status=graph_status,
        )

        warnings = warnings_for_readiness(
            derived=derived,
            outbox_by_type=outbox_by_type,
            evidence_enabled=self._evidence_enabled,
            graph_enabled=self._graph_enabled,
        )
        ready = profile_ready(
            profile=command.profile,
            source_events=source_readiness,
            derived=derived,
        )
        return PipelineReadinessResult(
            ready=ready,
            profile=command.profile,
            source_events=source_readiness,
            outbox=outbox_status,
            derived=derived,
            warnings=warnings,
            timed_out=False,
            trace_id=_trace_id(command),
        )

    async def await_ready(
        self,
        command: PipelineReadinessCommand,
        *,
        timeout_seconds: float,
    ) -> PipelineReadinessResult:
        if timeout_seconds < 0:
            raise ValueError("pipeline await timeout_seconds must be non-negative")
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last = await self.check(command)
        while (
            not last.ready
            and not profile_terminally_blocked(profile=command.profile, derived=last.derived)
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(min(self._poll_interval_seconds, max(0.0, deadline - asyncio.get_running_loop().time())))
            last = await self.check(command)
        if last.ready or profile_terminally_blocked(profile=command.profile, derived=last.derived):
            return last
        return replace(last, timed_out=True)


def _indexed_evidence_count(
    *,
    stored_count: int,
    source_event_count: int,
    evidence_status: JobStatusCount | None,
) -> int:
    if stored_count > 0 or evidence_status is None:
        return stored_count
    if evidence_status.ready:
        return min(evidence_status.succeeded, source_event_count)
    return stored_count


async def _load_available_source_events(
    source_repository: object,
    source_event_ids: tuple[str, ...],
    scope: EffectiveScope,
) -> dict[str, SourceEvent]:
    events: dict[str, SourceEvent] = {}
    for source_event_id in source_event_ids:
        event = await source_repository.get_source_event(source_event_id)
        if (
            event is not None
            and event.purged_at is None
            and event.purge_level == "none"
            and source_event_visible_in_scope(event, scope)
        ):
            events[event.id] = event
    return events


async def _related_outbox_jobs(
    outbox_repository: object,
    source_events: Iterable[SourceEvent],
    *,
    scope: EffectiveScope,
) -> tuple[OutboxJob, ...]:
    events = tuple(source_events)
    if not events:
        return ()
    direct = await outbox_repository.list_for_source_events(
        project_memory_space_id=scope.project_memory_space_id,
        source_event_ids=tuple(event.id for event in events),
    )
    scope_jobs = await outbox_repository.list_for_project_type_and_aggregates(
        project_memory_space_id=scope.project_memory_space_id,
        job_type=PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
        aggregate_keys=(
            aggregate_key_for_scope_job(
                scope=scope,
                job_type=PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
            ),
        ),
    )
    ltf_jobs = await outbox_repository.list_for_project_type_and_aggregates(
        project_memory_space_id=scope.project_memory_space_id,
        job_type=LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
        aggregate_keys=(
            aggregate_key_for_scope_job(
                scope=scope,
                job_type=LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
            ),
        ),
    )
    by_id = {job.id: job for job in direct}
    by_id.update({job.id: job for job in scope_jobs})
    by_id.update({job.id: job for job in ltf_jobs})
    return tuple(by_id.values())


async def _memory_items_for_source_events(
    repository: object,
    *,
    source_event_ids: tuple[str, ...],
    scope: EffectiveScope,
) -> tuple[MemoryItem, ...]:
    by_id: dict[str, MemoryItem] = {}
    for source_event_id in source_event_ids:
        for item in await repository.list_by_source_event(source_event_id):
            if (
                memory_item_visible_in_scope(item, scope)
                and is_current_recallable_memory_item(item)
            ):
                by_id[item.id] = item
    return tuple(by_id.values())


@dataclass(frozen=True, slots=True)
class _PageMemoryCoverage:
    pages: tuple[PageMemory, ...]
    matched_source_event_ids: tuple[str, ...]
    unmatched_source_event_ids: tuple[str, ...]


def _page_memory_coverage(
    pages: tuple[PageMemory, ...],
    *,
    source_event_ids: tuple[str, ...],
) -> _PageMemoryCoverage:
    expected = tuple(dict.fromkeys(source_event_ids))
    if not expected:
        return _PageMemoryCoverage(
            pages=(),
            matched_source_event_ids=(),
            unmatched_source_event_ids=(),
        )
    expected_set = set(expected)
    matched_ids: list[str] = []
    matched_pages: list[PageMemory] = []
    for page in pages:
        if page.needs_rebuild:
            continue
        page_matches = tuple(source_event_id for source_event_id in page.source_event_ids if source_event_id in expected_set)
        if not page_matches:
            continue
        matched_pages.append(page)
        matched_ids.extend(page_matches)
    matched = tuple(dict.fromkeys(matched_ids))
    matched_set = set(matched)
    return _PageMemoryCoverage(
        pages=tuple(matched_pages),
        matched_source_event_ids=matched,
        unmatched_source_event_ids=tuple(source_event_id for source_event_id in expected if source_event_id not in matched_set),
    )


def _trace_id(command: PipelineReadinessCommand) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(
                (
                    "pipeline_readiness",
                    command.profile.value,
                    command.scope.project_memory_space_id,
                    *command.source_event_ids,
                )
            ),
        )
    )
