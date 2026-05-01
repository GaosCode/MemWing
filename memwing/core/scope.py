from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryScope:
    project_memory_space_id: str
    group_id: str | None = None
    thread_id: str | None = None
    shared_group_id: str | None = None


@dataclass(frozen=True, slots=True)
class EffectiveScope:
    project_memory_space_id: str
    group_ids: tuple[str, ...] | None
    thread_id: str | None
    shared_group_id: str | None
    safe_mode_enabled: bool
    cross_group_allowed: bool


@dataclass(frozen=True, slots=True)
class ProjectMemorySpace:
    id: str
    name: str
    default_safe_mode_enabled: bool


@dataclass(frozen=True, slots=True)
class RuntimeScopeBinding:
    runtime: str
    agent_id: str
    workspace_id: str | None
    session_key_pattern: str
    project_memory_space_id: str


@dataclass(frozen=True, slots=True)
class PlatformScopeBinding:
    platform: str
    tenant_id: str | None
    channel_id: str
    thread_id: str | None
    project_memory_space_id: str
    group_id: str


@dataclass(frozen=True, slots=True)
class GroupMemorySettings:
    project_memory_space_id: str
    group_id: str
    safe_mode_enabled: bool
    shared_group_id: str | None


def effective_scope_matches(
    *,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
    scope: EffectiveScope,
) -> bool:
    if scope.group_ids is not None and group_id not in scope.group_ids:
        return False
    if scope.thread_id is not None and thread_id != scope.thread_id:
        return False
    if scope.shared_group_id is not None and shared_group_id != scope.shared_group_id:
        return False
    return True
