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
