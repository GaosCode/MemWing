from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Callable

from memwing.application.control_projection import (
    ControlPageDetailProjection,
    ControlPageListProjection,
    project_page,
    project_page_version,
)
from memwing.application.control_service_support import (
    _audit_event,
    _not_found,
    _rejected_audit_event,
    _scope_values_match,
    _uuid,
)
from memwing.core.models import MemoryPageVersion, PageMemory, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import EventStoreTransactionPort, EventStoreUnitOfWorkPort


class ControlPageServiceMixin:
    _unit_of_work: EventStoreUnitOfWorkPort
    _now: Callable[[], datetime]

    async def list_pages(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> ControlPageListProjection:
        async with self._unit_of_work.transaction() as tx:
            pages = await tx.memory_pages.list_for_scope(scope=scope, limit=limit)
            projections = []
            for page in pages:
                source_events = await _source_events_for_page(tx, page)
                projections.append(project_page(page, source_events=source_events))
        return ControlPageListProjection(items=tuple(projections), next_cursor=None, trace_id=trace_id)

    async def get_page_detail(
        self,
        *,
        page_id: str,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
    ) -> ControlPageDetailProjection:
        async with self._unit_of_work.transaction() as tx:
            page = await tx.memory_pages.get(page_id)
            if page is None or not _page_in_scope(page, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_page_detail",
                        entity_id=page_id,
                        trace_id=trace_id,
                        now=self._now(),
                    )
                )
                raise _not_found()
            source_events = await _source_events_for_page(tx, page)
            versions = await tx.memory_page_versions.list_by_page(page_id=page.id, limit=limit)
            audit_events = await tx.audit_events.list_for_entity(
                entity_type="memory_page",
                entity_id=page.id,
                limit=limit,
            )
        return ControlPageDetailProjection(
            page=project_page(page, source_events=source_events),
            versions=tuple(project_page_version(version) for version in versions),
            audit_refs=tuple(event.id for event in audit_events),
            trace_id=trace_id,
        )

    async def edit_page(
        self,
        *,
        page_id: str,
        scope: EffectiveScope,
        title: str,
        brief: str,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlPageDetailProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="memory_page",
                entity_id=page_id,
                idempotency_key=idempotency_key,
            )
            page = await tx.memory_pages.get_for_update(page_id)
            if page is None or not _page_in_scope(page, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_page_mutation",
                        entity_id=page_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()
            if existing_audit is None:
                updated = replace(
                    page,
                    title=title,
                    brief=brief,
                    version=page.version + 1,
                    updated_at=now,
                )
                page = await tx.memory_pages.upsert(updated)
                await tx.memory_page_versions.record(_page_version(page, changed_by="user", reason=reason, now=now))
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="memory_page",
                        entity_id=page.id,
                        stage="control.page.updated",
                        decision="updated",
                        reason_text=reason,
                        source_event_ids=page.source_event_ids,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                    )
                )
        return await self.get_page_detail(page_id=page_id, scope=scope, limit=20, trace_id=trace_id)

    async def restore_page_version(
        self,
        *,
        page_id: str,
        version: int,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlPageDetailProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="memory_page",
                entity_id=page_id,
                idempotency_key=idempotency_key,
            )
            page = await tx.memory_pages.get_for_update(page_id)
            restore_version = await tx.memory_page_versions.get(page_id, version)
            if page is None or restore_version is None or not _page_in_scope(page, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_page_restore",
                        entity_id=page_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()
            if existing_audit is None:
                restored = replace(
                    page,
                    title=restore_version.title,
                    brief=restore_version.brief,
                    topics=restore_version.topics,
                    open_questions=restore_version.open_questions,
                    next_steps=restore_version.next_steps,
                    source_event_ids=restore_version.source_event_ids,
                    linked_memory_item_ids=restore_version.linked_memory_item_ids,
                    version=page.version + 1,
                    updated_at=now,
                )
                page = await tx.memory_pages.upsert(restored)
                await tx.memory_page_versions.record(_page_version(page, changed_by="user", reason=reason, now=now))
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="memory_page",
                        entity_id=page.id,
                        stage="control.page.restored",
                        decision="restored",
                        reason_text=reason,
                        source_event_ids=page.source_event_ids,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                    )
                )
        return await self.get_page_detail(page_id=page_id, scope=scope, limit=20, trace_id=trace_id)


def _page_in_scope(page: PageMemory, scope: EffectiveScope) -> bool:
    return page.project_memory_space_id == scope.project_memory_space_id and _scope_values_match(
        group_id=page.group_id,
        thread_id=page.thread_id,
        shared_group_id=page.shared_group_id,
        scope=scope,
    )


async def _source_events_for_page(
    tx: EventStoreTransactionPort,
    page: PageMemory,
) -> tuple[SourceEvent, ...]:
    events: list[SourceEvent] = []
    for source_event_id in page.source_event_ids:
        event = await tx.source_events.get_source_event(source_event_id)
        if event is not None:
            events.append(event)
    return tuple(events)


def _page_version(page: PageMemory, *, changed_by: str, reason: str, now: datetime) -> MemoryPageVersion:
    return MemoryPageVersion(
        id=_uuid("memory_page_version", page.id, str(page.version)),
        page_id=page.id,
        version=page.version,
        title=page.title,
        brief=page.brief,
        topics=page.topics,
        open_questions=page.open_questions,
        next_steps=page.next_steps,
        source_event_ids=page.source_event_ids,
        linked_memory_item_ids=page.linked_memory_item_ids,
        changed_by=changed_by,
        change_reason=reason,
        created_at=now,
    )
