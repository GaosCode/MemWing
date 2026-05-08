from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ControlSettingsProjection:
    project_memory_space_id: str
    safe_mode_enabled: bool
    shared_group_id: str | None
    settings_mutation_supported: bool
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlIntegrationProjection:
    name: str
    configured: bool
    writable: bool


@dataclass(frozen=True, slots=True)
class ControlIntegrationsProjection:
    items: tuple[ControlIntegrationProjection, ...]
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlScopeThreadProjection:
    thread_id: str
    memory_count: int
    source_event_count: int
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ControlScopeGroupProjection:
    group_id: str
    safe_mode_enabled: bool
    shared_group_id: str | None
    memory_count: int
    source_event_count: int
    threads: tuple[ControlScopeThreadProjection, ...]


@dataclass(frozen=True, slots=True)
class ControlScopeDirectoryItemProjection:
    project_memory_space_id: str
    name: str
    kind: str
    default_safe_mode_enabled: bool
    memory_count: int
    source_event_count: int
    page_count: int
    updated_at: datetime | None
    groups: tuple[ControlScopeGroupProjection, ...]


@dataclass(frozen=True, slots=True)
class ControlScopeDirectoryProjection:
    items: tuple[ControlScopeDirectoryItemProjection, ...]
    next_cursor: str | None
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlResolvedScopeProjection:
    project_memory_space_id: str
    group_ids: tuple[str, ...] | None
    thread_id: str | None
    shared_group_id: str | None
    safe_mode_enabled: bool
    cross_group_allowed: bool


@dataclass(frozen=True, slots=True)
class ControlScopeProjectProjection:
    project_memory_space_id: str
    name: str
    kind: str


@dataclass(frozen=True, slots=True)
class ControlScopeResolveProjection:
    requested_scope: object
    effective_scope: ControlResolvedScopeProjection
    project: ControlScopeProjectProjection
    trace_id: str
