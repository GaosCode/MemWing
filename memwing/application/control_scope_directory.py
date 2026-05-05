from __future__ import annotations

from typing import Protocol

from memwing.application.control_projection import (
    ControlResolvedScopeProjection,
    ControlScopeDirectoryItemProjection,
    ControlScopeDirectoryProjection,
    ControlScopeGroupProjection,
    ControlScopeProjectProjection,
    ControlScopeResolveProjection,
    ControlScopeThreadProjection,
)
from memwing.core.scope import (
    MemoryScope,
    ProjectMemorySpace,
    ProjectMemorySpaceDirectoryGroupRecord,
    ProjectMemorySpaceDirectoryRecord,
)


class ControlScopeDirectoryStorePort(Protocol):
    async def get_project_memory_space(
        self,
        project_memory_space_id: str,
    ) -> ProjectMemorySpace | None:
        ...

    async def list_project_memory_space_directory(
        self,
        *,
        include_benchmark: bool,
        query: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[ProjectMemorySpaceDirectoryRecord, ...]:
        ...


class ControlScopeResolverPort(Protocol):
    async def resolve_control(self, scope_hint: MemoryScope):
        ...


class ControlScopeDirectory:
    def __init__(
        self,
        store: ControlScopeDirectoryStorePort,
        resolver: ControlScopeResolverPort,
    ) -> None:
        self._store = store
        self._resolver = resolver

    async def list_scopes(
        self,
        *,
        include_benchmark: bool,
        query: str | None,
        limit: int,
        cursor: str | None,
        trace_id: str,
    ) -> ControlScopeDirectoryProjection:
        records = await self._store.list_project_memory_space_directory(
            include_benchmark=include_benchmark,
            query=query,
            limit=limit,
            cursor=cursor,
        )
        return ControlScopeDirectoryProjection(
            items=tuple(_project_record(record) for record in records),
            next_cursor=None,
            trace_id=trace_id,
        )

    async def resolve_scope(
        self,
        *,
        scope_hint: MemoryScope,
        trace_id: str,
    ) -> ControlScopeResolveProjection:
        resolved = await self._resolver.resolve_control(scope_hint)
        project = await self._store.get_project_memory_space(scope_hint.project_memory_space_id)
        if project is None:
            raise ValueError("project memory space was not found after scope resolution")
        effective = resolved.effective_scope
        return ControlScopeResolveProjection(
            requested_scope=scope_hint,
            effective_scope=ControlResolvedScopeProjection(
                project_memory_space_id=effective.project_memory_space_id,
                group_ids=effective.group_ids,
                thread_id=effective.thread_id,
                shared_group_id=effective.shared_group_id,
                safe_mode_enabled=effective.safe_mode_enabled,
                cross_group_allowed=effective.cross_group_allowed,
            ),
            project=ControlScopeProjectProjection(
                project_memory_space_id=project.id,
                name=project.name,
                kind="benchmark" if project.id.startswith("benchmark:") else "project",
            ),
            trace_id=trace_id,
        )


def _project_record(record: ProjectMemorySpaceDirectoryRecord) -> ControlScopeDirectoryItemProjection:
    project = record.project
    return ControlScopeDirectoryItemProjection(
        project_memory_space_id=project.id,
        name=project.name,
        kind="benchmark" if project.id.startswith("benchmark:") else "project",
        default_safe_mode_enabled=project.default_safe_mode_enabled,
        memory_count=record.memory_count,
        source_event_count=record.source_event_count,
        page_count=record.page_count,
        updated_at=record.updated_at,
        groups=tuple(_group_record(group) for group in record.groups),
    )


def _group_record(group: ProjectMemorySpaceDirectoryGroupRecord) -> ControlScopeGroupProjection:
    return ControlScopeGroupProjection(
        group_id=group.group_id,
        safe_mode_enabled=group.safe_mode_enabled,
        shared_group_id=group.shared_group_id,
        memory_count=group.memory_count,
        source_event_count=group.source_event_count,
        threads=tuple(
            ControlScopeThreadProjection(
                thread_id=thread.thread_id,
                memory_count=thread.memory_count,
                source_event_count=thread.source_event_count,
                updated_at=thread.updated_at,
            )
            for thread in group.threads
        ),
    )
