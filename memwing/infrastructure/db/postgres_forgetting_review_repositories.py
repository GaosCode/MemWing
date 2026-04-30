from __future__ import annotations

from memwing.core.models import ForgettingReviewCandidate

from .postgres_derived_rows import forgetting_review_candidate_from_row
from .postgres_derived_sql import (
    _LIST_PENDING_FORGETTING_REVIEW_CANDIDATES_SQL,
    _UPSERT_FORGETTING_REVIEW_CANDIDATE_SQL,
)
from .postgres_repositories import PostgresExecutor


class PostgresForgettingReviewCandidateRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def upsert(
        self,
        candidate: ForgettingReviewCandidate,
    ) -> ForgettingReviewCandidate:
        row = await self._executor.fetchrow(
            _UPSERT_FORGETTING_REVIEW_CANDIDATE_SQL,
            _forgetting_review_candidate_params(candidate),
        )
        if row is None:
            raise RuntimeError("forgetting review candidate upsert did not return a row")
        return forgetting_review_candidate_from_row(row)

    async def list_pending(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[ForgettingReviewCandidate, ...]:
        rows = await self._executor.fetch(
            _LIST_PENDING_FORGETTING_REVIEW_CANDIDATES_SQL,
            {
                "project_memory_space_id": project_memory_space_id,
                "limit": limit,
            },
        )
        return tuple(forgetting_review_candidate_from_row(row) for row in rows)


def _forgetting_review_candidate_params(
    candidate: ForgettingReviewCandidate,
) -> dict[str, object]:
    return {
        "id": candidate.id,
        "memory_id": candidate.memory_id,
        "project_memory_space_id": candidate.project_memory_space_id,
        "group_id": candidate.group_id,
        "thread_id": candidate.thread_id,
        "decayed_score": candidate.decayed_score,
        "threshold": candidate.threshold,
        "reason": candidate.reason,
        "status": candidate.status,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
    }
