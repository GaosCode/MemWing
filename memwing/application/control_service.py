from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable
import uuid

from memwing.application.control_projection import (
    ControlForgettingReviewItemProjection,
    ControlForgettingReviewProjection,
    ControlMaintenanceProjection,
    ControlMemoryDetailProjection,
    ControlMemoryListProjection,
    project_graph_job,
    project_graph_link,
    project_memory_item,
    project_outbox_job,
    project_push_candidate,
)
from memwing.core.errors import ScopeResolutionFailure
from memwing.core.models import AuditEvent, MemoryItem, SourceEvent
from memwing.core.scope import EffectiveScope, effective_scope_matches
from memwing.ports.event_store import EventStoreTransactionPort, EventStoreUnitOfWorkPort


class ControlService:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._now = now or (lambda: datetime.now(UTC))

    async def list_memories(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> ControlMemoryListProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            items = await tx.memory_items.list_for_scope(scope=scope, limit=limit)
            projections = []
            for item in items:
                source_events = await _source_events_for_item(tx, item)
                graph_links = await tx.memory_graph_links.list_by_memory(item.id)
                projections.append(
                    project_memory_item(
                        item,
                        source_events=source_events,
                        graph_links=graph_links,
                        now=now,
                    )
                )
        return ControlMemoryListProjection(
            items=tuple(projections),
            next_cursor=None,
            trace_id=trace_id,
        )

    async def get_memory_detail(
        self,
        *,
        memory_id: str,
        scope: EffectiveScope,
        trace_id: str,
    ) -> ControlMemoryDetailProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            item = await tx.memory_items.get(memory_id)
            if item is None or not _memory_item_in_scope(item, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        memory_id=memory_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()

            source_events = await _source_events_for_item(tx, item)
            graph_links = await tx.memory_graph_links.list_by_memory(item.id)
            audit_events = await tx.audit_events.list_for_entity(
                entity_type="memory_item",
                entity_id=item.id,
                limit=20,
            )

        return ControlMemoryDetailProjection(
            item=project_memory_item(
                item,
                source_events=source_events,
                graph_links=graph_links,
                now=now,
            ),
            content=item.content,
            source_event_ids=item.source_event_ids,
            memory_item_ids=(item.id,),
            graph_links=tuple(project_graph_link(link) for link in graph_links),
            audit_refs=tuple(event.id for event in audit_events),
            trace_id=trace_id,
        )

    async def list_forgetting_review(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> ControlForgettingReviewProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            candidates = await tx.forgetting_review_candidates.list_pending(
                project_memory_space_id=scope.project_memory_space_id,
                limit=limit,
            )
            projections = []
            for candidate in candidates:
                item = await tx.memory_items.get(candidate.memory_id)
                if item is None or not _memory_item_in_scope(item, scope):
                    continue
                source_events = await _source_events_for_item(tx, item)
                graph_links = await tx.memory_graph_links.list_by_memory(item.id)
                projections.append(
                    ControlForgettingReviewItemProjection(
                        id=candidate.id,
                        memory=project_memory_item(
                            item,
                            source_events=source_events,
                            graph_links=graph_links,
                            now=now,
                            recall_threshold=candidate.threshold,
                        ),
                        threshold=candidate.threshold,
                        reason=candidate.reason,
                        created_at=candidate.created_at,
                        updated_at=candidate.updated_at,
                    )
                )
        return ControlForgettingReviewProjection(
            items=tuple(projections),
            next_cursor=None,
            trace_id=trace_id,
        )

    async def get_maintenance(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> ControlMaintenanceProjection:
        async with self._unit_of_work.transaction() as tx:
            forgetting_reviews = await tx.forgetting_review_candidates.list_pending(
                project_memory_space_id=scope.project_memory_space_id,
                limit=limit,
            )
            scoped_forgetting_reviews = []
            for candidate in forgetting_reviews:
                item = await tx.memory_items.get(candidate.memory_id)
                if item is not None and _memory_item_in_scope(item, scope):
                    scoped_forgetting_reviews.append(candidate)
            push_candidates = tuple(
                candidate
                for candidate in await tx.push_candidates.list_for_project(
                    project_memory_space_id=scope.project_memory_space_id,
                    limit=limit,
                )
                if _scope_values_match(
                    group_id=candidate.group_id,
                    thread_id=candidate.thread_id,
                    shared_group_id=candidate.shared_group_id,
                    scope=scope,
                )
            )
            graph_jobs = await tx.graph_write_jobs.list_for_project(
                project_memory_space_id=scope.project_memory_space_id,
                limit=limit,
            )
            outbox_jobs = await tx.outbox_jobs.list_for_project(
                project_memory_space_id=scope.project_memory_space_id,
                limit=limit,
            )

        pending_push_count = sum(1 for candidate in push_candidates if candidate.status == "pending")
        jobs = tuple(project_graph_job(job) for job in graph_jobs) + tuple(
            project_outbox_job(job) for job in outbox_jobs
        )
        jobs = jobs[:limit]
        return ControlMaintenanceProjection(
            forgetting_review_count=len(scoped_forgetting_reviews),
            pending_push_count=pending_push_count,
            job_count=len(jobs),
            warning_count=sum(1 for job in jobs if job.status == "dead_letter"),
            jobs=jobs,
            push_candidates=tuple(project_push_candidate(candidate) for candidate in push_candidates),
            trace_id=trace_id,
        )


async def _source_events_for_item(
    tx: EventStoreTransactionPort,
    item: MemoryItem,
) -> tuple[SourceEvent, ...]:
    events: list[SourceEvent] = []
    for source_event_id in item.source_event_ids:
        event = await tx.source_events.get_source_event(source_event_id)
        if event is not None:
            events.append(event)
    return tuple(events)


def _memory_item_in_scope(item: MemoryItem, scope: EffectiveScope) -> bool:
    return item.project_memory_space_id == scope.project_memory_space_id and _scope_values_match(
        group_id=item.group_id,
        thread_id=item.thread_id,
        shared_group_id=item.shared_group_id,
        scope=scope,
    )


def _scope_values_match(
    *,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
    scope: EffectiveScope,
) -> bool:
    return effective_scope_matches(
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
        scope=scope,
    )


def _not_found() -> ScopeResolutionFailure:
    return ScopeResolutionFailure(
        "control_projection_not_found",
        "The requested control plane resource was not found.",
    )


def _rejected_audit_event(*, memory_id: str, trace_id: str, now: datetime) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid4()),
        trace_id=trace_id,
        entity_type="control_memory_detail",
        entity_id=memory_id,
        stage="control.memory_detail.rejected",
        input_ref=memory_id,
        output_ref=None,
        decision="rejected",
        reason_code="control_projection_not_found",
        reason_text=None,
        source_event_ids=(),
        latency_ms=None,
        created_at=now,
        actor_id=None,
        idempotency_key=None,
        action_ref=None,
        lifecycle_revision=None,
    )
