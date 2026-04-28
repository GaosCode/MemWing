from __future__ import annotations

from dataclasses import dataclass, field

from memwing.core.models import AuditEvent, OutboxJob, SourceEvent
from memwing.core.scope import (
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)


@dataclass(slots=True)
class InMemoryState:
    source_events: dict[str, SourceEvent] = field(default_factory=dict)
    source_by_raw_hash: dict[tuple[str, str], str] = field(default_factory=dict)
    source_by_runtime_key: dict[tuple[str, str], str] = field(default_factory=dict)
    audit_events: dict[str, AuditEvent] = field(default_factory=dict)
    outbox_jobs: dict[str, OutboxJob] = field(default_factory=dict)
    outbox_by_idempotency_key: dict[str, str] = field(default_factory=dict)
    projects: dict[str, ProjectMemorySpace] = field(default_factory=dict)
    runtime_bindings: list[RuntimeScopeBinding] = field(default_factory=list)
    platform_bindings: list[PlatformScopeBinding] = field(default_factory=list)
    group_settings: dict[tuple[str, str], GroupMemorySettings] = field(default_factory=dict)
