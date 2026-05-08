from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from memwing.core.models import GraphWriteJob, MemoryGraphLink


class GraphWriteJobRepositoryPort(Protocol):
    async def enqueue(self, job: GraphWriteJob) -> GraphWriteJob:
        ...

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
        sort: str | None = None,
    ) -> tuple[GraphWriteJob, ...]:
        ...

    async def list_for_source_events(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
    ) -> tuple[GraphWriteJob, ...]:
        ...

    async def claim_pending(
        self,
        *,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
        max_project_concurrency: int = 1,
    ) -> tuple[GraphWriteJob, ...]:
        ...

    async def claim_pending_for_project(
        self,
        *,
        project_memory_space_id: str,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
        max_project_concurrency: int = 1,
    ) -> tuple[GraphWriteJob, ...]:
        ...

    async def mark_succeeded(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
    ) -> GraphWriteJob:
        ...

    async def extend_lock(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        lock_duration: timedelta,
    ) -> GraphWriteJob:
        ...

    async def mark_failed(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
        retry_delay: timedelta,
    ) -> GraphWriteJob:
        ...

    async def mark_dead_letter(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
    ) -> GraphWriteJob:
        ...

    async def retry_dead_letter(
        self,
        *,
        job_id: str,
        project_memory_space_id: str,
        now: datetime,
    ) -> GraphWriteJob | None:
        ...


class MemoryGraphLinkRepositoryPort(Protocol):
    async def upsert(self, link: MemoryGraphLink) -> MemoryGraphLink:
        ...

    async def list_by_memory(self, memory_id: str) -> tuple[MemoryGraphLink, ...]:
        ...

    async def list_by_backend_objects(
        self,
        *,
        project_memory_space_id: str,
        backend: str,
        backend_object_type: str,
        backend_object_ids: tuple[str, ...],
    ) -> tuple[MemoryGraphLink, ...]:
        ...
