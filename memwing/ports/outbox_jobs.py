from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from memwing.core.models import OutboxJob


class EventStoreError(RuntimeError):
    pass


class OutboxLockOwnershipError(EventStoreError):
    pass


class OutboxJobRepositoryPort(Protocol):
    async def enqueue(self, job: OutboxJob) -> OutboxJob:
        ...

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
        sort: str | None = None,
    ) -> tuple[OutboxJob, ...]:
        ...

    async def list_for_source_events(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
    ) -> tuple[OutboxJob, ...]:
        ...

    async def list_for_project_type_and_aggregates(
        self,
        *,
        project_memory_space_id: str,
        job_type: str,
        aggregate_keys: tuple[str, ...],
    ) -> tuple[OutboxJob, ...]:
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

    async def claim_pending_for_project(
        self,
        *,
        project_memory_space_id: str,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        ...

    async def claim_pending_for_types(
        self,
        *,
        job_types: tuple[str, ...],
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        ...

    async def claim_pending_for_project_and_type(
        self,
        *,
        project_memory_space_id: str,
        job_type: str,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        ...

    async def claim_pending_for_project_type_and_aggregate(
        self,
        *,
        project_memory_space_id: str,
        job_type: str,
        aggregate_key: str,
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

    async def retry_dead_letter(
        self,
        *,
        job_id: str,
        project_memory_space_id: str,
        now: datetime,
    ) -> OutboxJob | None:
        ...
