from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable, Mapping

from memwing.application.control_memory_service import (
    ControlMemoryServiceMixin,
    _memory_item_in_scope,
    _source_events_for_item,
)
from memwing.application.control_manual_memory_service import ControlManualMemoryServiceMixin
from memwing.application.control_page_service import ControlPageServiceMixin
from memwing.application.control_pagination import (
    control_fetch_limit,
    paginate_control_items,
)
from memwing.application.control_projection import (
    ControlIntegrationsProjection,
    ControlIntegrationProjection,
    ControlForgettingReviewItemProjection,
    ControlForgettingReviewProjection,
    ControlMaintenanceProjection,
    ControlScopeDirectoryProjection,
    ControlScopeResolveProjection,
    ControlSettingsProjection,
    ControlSummaryProjection,
    project_graph_job,
    project_memory_item,
    project_outbox_job,
    project_push_candidate,
)
from memwing.application.control_scope_directory import ControlScopeDirectory
from memwing.application.control_push_service import ControlPushServiceMixin
from memwing.application.control_service_support import (
    _audit_event,
    _not_found,
    _rejected_audit_event,
    _scope_values_match,
)
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.scope import EffectiveScope, MemoryScope
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.platform_connector import PlatformConnectorPort


class ControlService(
    ControlManualMemoryServiceMixin,
    ControlMemoryServiceMixin,
    ControlPageServiceMixin,
    ControlPushServiceMixin,
):
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        now: Callable[[], datetime] | None = None,
        page_memory_service: object | None = None,
        platform_connectors: Mapping[str, PlatformConnectorPort] | None = None,
        scope_resolver: ScopeResolver | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._now = now or (lambda: datetime.now(UTC))
        self._lifecycle = LifecycleTransitionService(unit_of_work)
        self._page_memory_service = page_memory_service
        self._platform_connectors = platform_connectors or {}
        self._scope_directory = ControlScopeDirectory(
            unit_of_work,
            scope_resolver or ScopeResolver(unit_of_work),
        )

    async def list_scopes(
        self,
        *,
        include_benchmark: bool,
        query: str | None,
        limit: int,
        cursor: str | None,
        trace_id: str,
    ) -> ControlScopeDirectoryProjection:
        return await self._scope_directory.list_scopes(
            include_benchmark=include_benchmark,
            query=query,
            limit=limit,
            cursor=cursor,
            trace_id=trace_id,
        )

    async def resolve_scope(
        self,
        *,
        scope_hint: MemoryScope,
        trace_id: str,
    ) -> ControlScopeResolveProjection:
        return await self._scope_directory.resolve_scope(scope_hint=scope_hint, trace_id=trace_id)

    async def list_forgetting_review(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
        cursor: str | None = None,
        sort: str = "updated_at",
    ) -> ControlForgettingReviewProjection:
        now = self._now()
        fetch_limit = control_fetch_limit(limit=limit, cursor=cursor)
        async with self._unit_of_work.transaction() as tx:
            candidates = await tx.forgetting_review_candidates.list_pending(
                project_memory_space_id=scope.project_memory_space_id,
                limit=fetch_limit,
                sort=sort,
            )
            scoped_candidates = []
            for candidate in candidates:
                item = await tx.memory_items.get(candidate.memory_id)
                if item is None or not _memory_item_in_scope(item, scope):
                    continue
                scoped_candidates.append((candidate, item))
            paged = paginate_control_items(
                scoped_candidates,
                limit=limit,
                cursor=cursor,
                sort=sort,
                key=lambda pair: (_forgetting_review_sort_value(pair[0], sort), pair[0].id),
            )
            projections = []
            for candidate, item in paged.items:
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
            next_cursor=paged.next_cursor,
            trace_id=trace_id,
        )

    async def get_maintenance(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
        cursor: str | None = None,
        jobs_cursor: str | None = None,
        push_candidates_cursor: str | None = None,
        sort: str = "updated_at",
    ) -> ControlMaintenanceProjection:
        effective_jobs_cursor = jobs_cursor if jobs_cursor is not None else cursor
        effective_push_candidates_cursor = (
            push_candidates_cursor if push_candidates_cursor is not None else cursor
        )
        jobs_fetch_limit = control_fetch_limit(limit=limit, cursor=effective_jobs_cursor)
        push_candidates_fetch_limit = control_fetch_limit(
            limit=limit,
            cursor=effective_push_candidates_cursor,
        )
        async with self._unit_of_work.transaction() as tx:
            forgetting_reviews = await tx.forgetting_review_candidates.list_pending(
                project_memory_space_id=scope.project_memory_space_id,
                limit=max(jobs_fetch_limit, push_candidates_fetch_limit),
                sort=sort,
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
                    limit=push_candidates_fetch_limit,
                    sort=sort,
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
                limit=jobs_fetch_limit,
                sort=sort,
            )
            outbox_jobs = await tx.outbox_jobs.list_for_project(
                project_memory_space_id=scope.project_memory_space_id,
                limit=jobs_fetch_limit,
                sort=sort,
            )

        pending_push_count = sum(1 for candidate in push_candidates if candidate.status == "pending")
        jobs = tuple(graph_jobs) + tuple(outbox_jobs)
        paged_jobs = paginate_control_items(
            jobs,
            limit=limit,
            cursor=effective_jobs_cursor,
            sort=sort,
            key=lambda job: (_job_sort_value(job, sort), _job_kind_rank(job), job.id),
        )
        paged_push_candidates = paginate_control_items(
            push_candidates,
            limit=limit,
            cursor=effective_push_candidates_cursor,
            sort=sort,
            key=lambda candidate: (_push_candidate_sort_value(candidate, sort), candidate.id),
        )
        return ControlMaintenanceProjection(
            forgetting_review_count=len(scoped_forgetting_reviews),
            pending_push_count=pending_push_count,
            job_count=len(paged_jobs.items),
            warning_count=sum(1 for job in paged_jobs.items if job.status == "dead_letter"),
            jobs=tuple(
                project_graph_job(job) if hasattr(job, "backend") else project_outbox_job(job)
                for job in paged_jobs.items
            ),
            push_candidates=tuple(
                project_push
                for project_push in (
                    project_push_candidate(candidate) for candidate in paged_push_candidates.items
                )
            ),
            jobs_next_cursor=paged_jobs.next_cursor,
            push_candidates_next_cursor=paged_push_candidates.next_cursor,
            next_cursor=paged_jobs.next_cursor or paged_push_candidates.next_cursor,
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


def _forgetting_review_sort_value(candidate: object, sort: str) -> object:
    if sort == "created_at":
        return getattr(candidate, "created_at")
    return getattr(candidate, "updated_at")


def _job_sort_value(job: object, sort: str) -> object:
    if sort == "created_at":
        return getattr(job, "created_at")
    if sort == "next_run_at":
        return getattr(job, "next_run_at")
    if sort == "priority":
        return getattr(job, "priority")
    return getattr(job, "updated_at")


def _job_kind_rank(job: object) -> int:
    return 1 if hasattr(job, "backend") else 0


def _push_candidate_sort_value(candidate: object, sort: str) -> object:
    if sort == "priority":
        return getattr(candidate, "priority")
    if sort == "created_at":
        return getattr(candidate, "created_at")
    return getattr(candidate, "updated_at")
