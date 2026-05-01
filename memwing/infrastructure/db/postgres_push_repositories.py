from __future__ import annotations

from datetime import datetime

from memwing.core.models import PushCandidate

from .postgres_derived_rows import push_candidate_from_row
from .postgres_derived_sql import (
    _GET_PUSH_CANDIDATE_SQL,
    _LIST_PENDING_PUSH_CANDIDATES_SQL,
    _LIST_PUSH_CANDIDATES_FOR_PROJECT_SQL,
    _UPDATE_PUSH_CANDIDATE_STATUS_SQL,
    _UPSERT_PUSH_CANDIDATE_SQL,
)
from .postgres_repositories import PostgresExecutor


class PostgresPushCandidateRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def upsert(self, candidate: PushCandidate) -> PushCandidate:
        row = await self._executor.fetchrow(
            _UPSERT_PUSH_CANDIDATE_SQL,
            _push_candidate_params(candidate),
        )
        if row is None:
            raise RuntimeError("push candidate upsert did not return a row")
        return push_candidate_from_row(row)

    async def get(self, candidate_id: str) -> PushCandidate | None:
        row = await self._executor.fetchrow(
            _GET_PUSH_CANDIDATE_SQL,
            {"candidate_id": candidate_id},
        )
        return push_candidate_from_row(row) if row is not None else None

    async def update_status(
        self,
        *,
        candidate_id: str,
        project_memory_space_id: str,
        status: str,
        updated_at: datetime,
    ) -> PushCandidate | None:
        row = await self._executor.fetchrow(
            _UPDATE_PUSH_CANDIDATE_STATUS_SQL,
            {
                "candidate_id": candidate_id,
                "project_memory_space_id": project_memory_space_id,
                "status": status,
                "updated_at": updated_at,
            },
        )
        return push_candidate_from_row(row) if row is not None else None

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PushCandidate, ...]:
        rows = await self._executor.fetch(
            _LIST_PUSH_CANDIDATES_FOR_PROJECT_SQL,
            {"project_memory_space_id": project_memory_space_id, "limit": limit},
        )
        return tuple(push_candidate_from_row(row) for row in rows)

    async def list_pending(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PushCandidate, ...]:
        rows = await self._executor.fetch(
            _LIST_PENDING_PUSH_CANDIDATES_SQL,
            {"project_memory_space_id": project_memory_space_id, "limit": limit},
        )
        return tuple(push_candidate_from_row(row) for row in rows)


def _push_candidate_params(candidate: PushCandidate) -> dict[str, object]:
    return {
        "id": candidate.id,
        "project_memory_space_id": candidate.project_memory_space_id,
        "group_id": candidate.group_id,
        "thread_id": candidate.thread_id,
        "shared_group_id": candidate.shared_group_id,
        "type": candidate.type,
        "title": candidate.title,
        "content": candidate.content,
        "memory_item_ids": candidate.memory_item_ids,
        "source_event_ids": candidate.source_event_ids,
        "trigger_reason": candidate.trigger_reason,
        "trigger_source": candidate.trigger_source,
        "priority": candidate.priority,
        "expires_at": candidate.expires_at,
        "status": candidate.status,
        "cooldown_key": candidate.cooldown_key,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
    }
