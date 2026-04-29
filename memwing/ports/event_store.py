from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from memwing.api.agent_runtime import RememberEventResult
from memwing.core.models import AuditEvent, OutboxJob, SourceEvent
from memwing.core.scope import (
    EffectiveScope,
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)


class EventStoreError(RuntimeError):
    pass


class OutboxLockOwnershipError(EventStoreError):
    pass


class SourceEventRepositoryPort(Protocol):
    async def insert_if_absent(self, event: SourceEvent) -> tuple[SourceEvent, bool]:
        ...

    async def get_source_event(self, source_event_id: str) -> SourceEvent | None:
        ...


class AuditEventRepositoryPort(Protocol):
    async def record(self, event: AuditEvent) -> AuditEvent:
        ...


class OutboxJobRepositoryPort(Protocol):
    async def enqueue(self, job: OutboxJob) -> OutboxJob:
        ...

    async def claim_pending(
        self,
        *,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        ...

    async def mark_succeeded(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
    ) -> OutboxJob:
        ...

    async def mark_failed(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
        retry_delay: timedelta,
    ) -> OutboxJob:
        ...


class EventStoreTransactionPort(Protocol):
    source_events: SourceEventRepositoryPort
    audit_events: AuditEventRepositoryPort
    outbox_jobs: OutboxJobRepositoryPort


class EventStoreUnitOfWorkPort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[EventStoreTransactionPort]:
        ...


class ScopeBindingStorePort(Protocol):
    async def get_project_memory_space(
        self, project_memory_space_id: str
    ) -> ProjectMemorySpace | None:
        ...

    async def list_runtime_scope_binding_candidates(
        self,
        *,
        runtime: str,
        agent_id: str,
        workspace_id: str | None,
        session_id: str | None,
    ) -> tuple[RuntimeScopeBinding, ...]:
        ...

    async def list_platform_scope_binding_candidates(
        self,
        *,
        platform: str,
        tenant_id: str | None,
        channel_id: str,
        thread_id: str | None,
    ) -> tuple[PlatformScopeBinding, ...]:
        ...

    async def get_group_memory_settings(
        self,
        *,
        project_memory_space_id: str,
        group_id: str,
    ) -> GroupMemorySettings | None:
        ...


@runtime_checkable
class EventStorePort(Protocol):
    async def remember_event(self, event: SourceEvent) -> RememberEventResult:
        ...

    async def get_source_event(
        self, source_event_id: str, scope: EffectiveScope
    ) -> SourceEvent | None:
        ...
