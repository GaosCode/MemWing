from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Callable

from memwing.application.control_pagination import control_fetch_limit, paginate_control_items
from memwing.application.control_projection import (
    ControlMemoryDetailProjection,
    ControlMemoryListProjection,
    ControlMemoryVersionProjection,
    ControlSourceEventDetailProjection,
    ControlSourceEventListProjection,
    project_graph_link,
    project_memory_item,
    project_memory_version,
    project_source_event,
)
from memwing.application.control_service_support import (
    _audit_event,
    _not_found,
    _rejected_audit_event,
    _uuid,
)
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import MemoryItem, MemoryVersion, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.core.scope_visibility import (
    memory_item_visible_in_scope,
    source_event_visible_in_scope,
)
from memwing.ports.event_store import (
    EventStoreTransactionPort,
    EventStoreUnitOfWorkPort,
    MemoryVersionRepositoryPort,
)
from memwing.ports.lifecycle_transition import LifecycleTransitionRequest


class ControlMemoryServiceMixin:
    _unit_of_work: EventStoreUnitOfWorkPort
    _now: Callable[[], datetime]
    _lifecycle: LifecycleTransitionService

    async def list_memories(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
        cursor: str | None = None,
        sort: str = "updated_at",
    ) -> ControlMemoryListProjection:
        now = self._now()
        fetch_limit = control_fetch_limit(limit=limit, cursor=cursor)
        async with self._unit_of_work.transaction() as tx:
            items = await tx.memory_items.list_for_scope(scope=scope, limit=fetch_limit, sort=sort)
            paged = paginate_control_items(
                items,
                limit=limit,
                cursor=cursor,
                sort=sort,
                key=lambda item: (_memory_sort_value(item, sort), item.id),
            )
            projections = []
            for item in paged.items:
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
            next_cursor=paged.next_cursor,
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

    async def edit_memory(
        self,
        *,
        memory_id: str,
        scope: EffectiveScope,
        title: str,
        content: str,
        summary: str | None,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlMemoryDetailProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="memory_item",
                entity_id=memory_id,
                idempotency_key=idempotency_key,
            )
            item = await tx.memory_items.get_for_update(memory_id)
            if item is None or not _memory_item_in_scope(item, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_memory_edit",
                        entity_id=memory_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()
            if existing_audit is None:
                item = await tx.memory_items.upsert(
                    replace(
                        item,
                        title=title,
                        content=content,
                        summary=summary,
                        updated_at=now,
                        lifecycle_revision=item.lifecycle_revision + 1,
                    )
                )
                await tx.memory_versions.record(
                    _memory_version(
                        item,
                        version=await _next_memory_version(tx.memory_versions, item.id),
                        changed_by="user",
                        reason=reason,
                        now=now,
                    )
                )
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="memory_item",
                        entity_id=item.id,
                        stage="control.memory.updated",
                        decision="updated",
                        reason_text=reason,
                        source_event_ids=item.source_event_ids,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                    )
                )
        return await self.get_memory_detail(memory_id=memory_id, scope=scope, trace_id=trace_id)

    async def restore_memory_version(
        self,
        *,
        memory_id: str,
        version: int,
        scope: EffectiveScope,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> ControlMemoryDetailProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            existing_audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="memory_item",
                entity_id=memory_id,
                idempotency_key=idempotency_key,
            )
            item = await tx.memory_items.get_for_update(memory_id)
            restore_version = await tx.memory_versions.get(memory_id, version)
            if item is None or restore_version is None or not _memory_item_in_scope(item, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_memory_restore",
                        entity_id=memory_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()
            if existing_audit is None:
                item = await tx.memory_items.upsert(
                    replace(
                        item,
                        title=restore_version.title,
                        content=restore_version.content,
                        summary=restore_version.summary,
                        source_event_ids=restore_version.source_event_ids,
                        status=restore_version.status,
                        updated_at=now,
                        lifecycle_revision=item.lifecycle_revision + 1,
                    )
                )
                await tx.memory_versions.record(
                    _memory_version(
                        item,
                        version=await _next_memory_version(tx.memory_versions, item.id),
                        changed_by="user",
                        reason=reason,
                        now=now,
                    )
                )
                await tx.audit_events.record(
                    _audit_event(
                        entity_type="memory_item",
                        entity_id=item.id,
                        stage="control.memory.restored",
                        decision="restored",
                        reason_text=reason,
                        source_event_ids=item.source_event_ids,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        trace_id=trace_id,
                        now=now,
                        output_ref=str(version),
                    )
                )
        return await self.get_memory_detail(memory_id=memory_id, scope=scope, trace_id=trace_id)

    async def list_source_events(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
        trace_id: str,
        cursor: str | None = None,
        sort: str = "event_time",
    ) -> ControlSourceEventListProjection:
        fetch_limit = control_fetch_limit(limit=limit, cursor=cursor)
        async with self._unit_of_work.transaction() as tx:
            events = await tx.source_events.list_for_scope(scope=scope, limit=fetch_limit)
            paged = paginate_control_items(
                events,
                limit=limit,
                cursor=cursor,
                sort=sort,
                key=lambda event: (_source_event_sort_value(event, sort), event.id),
            )
        return ControlSourceEventListProjection(
            items=tuple(project_source_event(event) for event in paged.items),
            next_cursor=paged.next_cursor,
            trace_id=trace_id,
        )

    async def get_source_event_detail(
        self,
        *,
        source_event_id: str,
        scope: EffectiveScope,
        trace_id: str,
    ) -> ControlSourceEventDetailProjection:
        now = self._now()
        async with self._unit_of_work.transaction() as tx:
            event = await tx.source_events.get_source_event(source_event_id)
            if event is None or not _source_event_in_scope(event, scope):
                await tx.audit_events.record(
                    _rejected_audit_event(
                        entity_type="control_source_event_detail",
                        entity_id=source_event_id,
                        trace_id=trace_id,
                        now=now,
                    )
                )
                raise _not_found()
            memory_items = await tx.memory_items.list_by_source_event(source_event_id)
            audit_events = await tx.audit_events.list_for_entity(
                entity_type="source_event",
                entity_id=source_event_id,
                limit=20,
            )
        return ControlSourceEventDetailProjection(
            source_event=project_source_event(event),
            memory_item_ids=tuple(
                item.id for item in memory_items if _memory_item_in_scope(item, scope)
            ),
            audit_refs=tuple(event.id for event in audit_events),
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


async def _next_memory_version(
    memory_versions: MemoryVersionRepositoryPort,
    memory_id: str,
) -> int:
    latest = await memory_versions.get_latest(memory_id)
    return 1 if latest is None else latest.version + 1


def _memory_version(
    item: MemoryItem,
    *,
    version: int,
    changed_by: str,
    reason: str,
    now: datetime,
) -> MemoryVersion:
    return MemoryVersion(
        id=_uuid("memory_version", item.id, str(version)),
        memory_id=item.id,
        version=version,
        title=item.title,
        content=item.content,
        summary=item.summary,
        status=item.status,
        source_event_ids=item.source_event_ids,
        changed_by=changed_by,
        change_reason=reason,
        created_at=now,
    )


def _memory_item_in_scope(item: MemoryItem, scope: EffectiveScope) -> bool:
    return memory_item_visible_in_scope(item, scope)


def _source_event_in_scope(event: SourceEvent, scope: EffectiveScope) -> bool:
    return source_event_visible_in_scope(event, scope)


def _memory_sort_value(item: object, sort: str) -> object:
    if sort == "event_time":
        return getattr(item, "event_time", None) or getattr(item, "updated_at")
    if sort == "created_at":
        return getattr(item, "created_at")
    return getattr(item, "updated_at")


def _source_event_sort_value(event: SourceEvent, sort: str) -> object:
    if sort == "created_at":
        return event.created_at
    return event.event_time
