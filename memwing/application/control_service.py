from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from memwing.application.control_page_service import ControlPageServiceMixin
from memwing.application.control_projection import (
    ControlIntegrationsProjection,
    ControlIntegrationProjection,
    ControlForgettingReviewItemProjection,
    ControlForgettingReviewProjection,
    ControlMaintenanceProjection,
    ControlMemoryDetailProjection,
    ControlMemoryListProjection,
    ControlMemoryVersionProjection,
    ControlSettingsProjection,
    ControlSummaryProjection,
    project_graph_job,
    project_graph_link,
    project_memory_item,
    project_memory_version,
    project_outbox_job,
    project_push_candidate,
)
from memwing.application.control_service_support import (
    _audit_event,
    _not_found,
    _rejected_audit_event,
    _scope_values_match,
)
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import MemoryItem, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import EventStoreTransactionPort, EventStoreUnitOfWorkPort
from memwing.ports.lifecycle_transition import LifecycleTransitionRequest


class ControlService(ControlPageServiceMixin):
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._now = now or (lambda: datetime.now(UTC))
        self._lifecycle = LifecycleTransitionService(unit_of_work)

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
                        entity_type="control_memory_detail",
                        entity_id=memory_id,
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

    async def list_memory_versions(
        self,
        *,
        memory_id: str,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> tuple[ControlMemoryVersionProjection, ...]:
        async with self._unit_of_work.transaction() as tx:
            item = await tx.memory_items.get(memory_id)
            if item is None or not _memory_item_in_scope(item, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_memory_versions",
                        entity_id=memory_id,
                        trace_id=trace_id,
                        now=self._now(),
                    )
                )
                raise _not_found()
            versions = await tx.memory_versions.list_by_memory(memory_id=memory_id, limit=limit)
        return tuple(project_memory_version(version) for version in versions)

    async def transition_memory(
        self,
        *,
        memory_id: str,
        action: LifecycleAction,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlMemoryDetailProjection:
        async with self._unit_of_work.transaction() as tx:
            item = await tx.memory_items.get(memory_id)
            if item is None or not _memory_item_in_scope(item, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_memory_mutation",
                        entity_id=memory_id,
                        trace_id=trace_id,
                        now=self._now(),
                    )
                )
                raise _not_found()
        await self._lifecycle.transition(
            LifecycleTransitionRequest(
                memory_id=memory_id,
                action=action,
                actor_id=actor_id,
                reason=reason,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                now=self._now(),
            )
        )
        return await self.get_memory_detail(memory_id=memory_id, scope=scope, trace_id=trace_id)

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

    async def get_summary(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> ControlSummaryProjection:
        maintenance = await self.get_maintenance(scope=scope, limit=limit, trace_id=trace_id)
        memory_list = await self.list_memories(scope=scope, limit=limit, trace_id=trace_id)
        pending_count = sum(
            1
            for item in memory_list.items
            if item.status.value in ("candidate", "needs_review") or item.curve_state == "below_threshold"
        )
        return ControlSummaryProjection(
            pending_memory_count=pending_count,
            forgetting_review_count=maintenance.forgetting_review_count,
            pending_push_count=maintenance.pending_push_count,
            dead_letter_job_count=sum(1 for job in maintenance.jobs if job.status == "dead_letter"),
            warning_count=maintenance.warning_count,
            trace_id=trace_id,
        )

    async def approve_push_candidate(
        self,
        *,
        candidate_id: str,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ):
        return await self._transition_push_candidate(
            candidate_id=candidate_id,
            scope=scope,
            next_status="approved",
            actor_id=actor_id,
            reason=reason,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    async def skip_push_candidate(
        self,
        *,
        candidate_id: str,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ):
        return await self._transition_push_candidate(
            candidate_id=candidate_id,
            scope=scope,
            next_status="skipped",
            actor_id=actor_id,
            reason=reason,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    async def retry_job(
        self,
        *,
        job_id: str,
        kind: str,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlMaintenanceProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type=f"{kind}_job",
                entity_id=job_id,
                idempotency_key=idempotency_key,
            )
            if existing_audit is None:
                if kind == "outbox":
                    updated = await tx.outbox_jobs.retry_dead_letter(
                        job_id=job_id,
                        project_memory_space_id=scope.project_memory_space_id,
                        now=now,
                    )
                elif kind == "graph_write":
                    updated = await tx.graph_write_jobs.retry_dead_letter(
                        job_id=job_id,
                        project_memory_space_id=scope.project_memory_space_id,
                        now=now,
                    )
                else:
                    updated = None
                if updated is None:
                    await tx.audit_events.record(
                        _rejected_audit_event(
                            entity_type="control_job_retry",
                            entity_id=job_id,
                            trace_id=trace_id,
                            now=now,
                        )
                    )
                    raise _not_found()
                await tx.audit_events.record(
                    _audit_event(
                        entity_type=f"{kind}_job",
                        entity_id=job_id,
                        stage="control.job.retry",
                        decision="retry",
                        reason_text=reason,
                        source_event_ids=(),
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                    )
                )
        return await self.get_maintenance(scope=scope, limit=20, trace_id=trace_id)

    async def get_settings(self, *, scope: EffectiveScope, trace_id: str) -> ControlSettingsProjection:
        return ControlSettingsProjection(
            project_memory_space_id=scope.project_memory_space_id,
            safe_mode_enabled=scope.safe_mode_enabled,
            shared_group_id=scope.shared_group_id,
            settings_mutation_supported=False,
            trace_id=trace_id,
        )

    async def get_integrations(self, *, trace_id: str) -> ControlIntegrationsProjection:
        return ControlIntegrationsProjection(
            items=(
                ControlIntegrationProjection(name="openclaw", configured=True, writable=False),
                ControlIntegrationProjection(name="feishu", configured=True, writable=False),
                ControlIntegrationProjection(name="graph_backend", configured=True, writable=False),
                ControlIntegrationProjection(name="llm_filter", configured=True, writable=False),
            ),
            trace_id=trace_id,
        )

    async def _transition_push_candidate(
        self,
        *,
        candidate_id: str,
        scope: EffectiveScope,
        next_status: str,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ):
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="push_candidate",
                entity_id=candidate_id,
                idempotency_key=idempotency_key,
            )
            candidate = await tx.push_candidates.get(candidate_id)
            if candidate is None or not _scope_values_match(
                group_id=candidate.group_id,
                thread_id=candidate.thread_id,
                shared_group_id=candidate.shared_group_id,
                scope=scope,
            ):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_push_candidate",
                        entity_id=candidate_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()
            if existing_audit is None:
                candidate = await tx.push_candidates.update_status(
                    candidate_id=candidate_id,
                    project_memory_space_id=scope.project_memory_space_id,
                    status=next_status,
                    updated_at=now,
                )
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="push_candidate",
                        entity_id=candidate_id,
                        stage=f"control.push_candidate.{next_status}",
                        decision=next_status,
                        reason_text=reason,
                        source_event_ids=candidate.source_event_ids if candidate is not None else (),
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                    )
                )
            if candidate is None:
                raise _not_found()
            return project_push_candidate(candidate)


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
