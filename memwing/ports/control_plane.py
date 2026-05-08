from __future__ import annotations

from datetime import datetime
from typing import Protocol

from memwing.core.models import ForgettingReviewCandidate, PushCandidate


class ForgettingReviewCandidateRepositoryPort(Protocol):
    async def upsert(
        self,
        candidate: ForgettingReviewCandidate,
    ) -> ForgettingReviewCandidate:
        ...

    async def list_pending(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
        sort: str | None = None,
    ) -> tuple[ForgettingReviewCandidate, ...]:
        ...


class PushCandidateRepositoryPort(Protocol):
    async def upsert(self, candidate: PushCandidate) -> PushCandidate:
        ...

    async def get(self, candidate_id: str) -> PushCandidate | None:
        ...

    async def update_status(
        self,
        *,
        candidate_id: str,
        project_memory_space_id: str,
        status: str,
        updated_at: datetime,
    ) -> PushCandidate | None:
        ...

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
        sort: str | None = None,
    ) -> tuple[PushCandidate, ...]:
        ...

    async def list_pending(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PushCandidate, ...]:
        ...
