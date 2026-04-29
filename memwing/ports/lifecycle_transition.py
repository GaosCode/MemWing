from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import AuditEvent, MemoryItem, MemoryStatus


@dataclass(frozen=True, slots=True)
class LifecycleTransitionRequest:
    memory_id: str
    action: LifecycleAction
    actor_id: str
    reason: str
    idempotency_key: str
    trace_id: str
    now: datetime


@dataclass(frozen=True, slots=True)
class LifecycleTransitionResult:
    memory_item: MemoryItem
    previous_status: MemoryStatus
    audit_event: AuditEvent


@runtime_checkable
class LifecycleTransitionPort(Protocol):
    async def transition(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransitionResult:
        ...
