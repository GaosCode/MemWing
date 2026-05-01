from __future__ import annotations

from dataclasses import replace

from memwing.core.models import PushCandidate

from .in_memory_transaction_view import InMemoryTransactionView


class InMemoryPushCandidateRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert(self, candidate: PushCandidate) -> PushCandidate:
        key = (candidate.cooldown_key, candidate.status)
        existing_id = self._tx.state.push_candidate_by_cooldown_status.get(key)
        if existing_id is not None:
            existing = self._tx.state.push_candidates[existing_id]
            updated = replace(
                existing,
                project_memory_space_id=candidate.project_memory_space_id,
                group_id=candidate.group_id,
                thread_id=candidate.thread_id,
                shared_group_id=candidate.shared_group_id,
                type=candidate.type,
                title=candidate.title,
                content=candidate.content,
                memory_item_ids=candidate.memory_item_ids,
                source_event_ids=candidate.source_event_ids,
                trigger_reason=candidate.trigger_reason,
                trigger_source=candidate.trigger_source,
                priority=candidate.priority,
                expires_at=candidate.expires_at,
                updated_at=candidate.updated_at,
            )
            self._tx.state.push_candidates[existing_id] = updated
            return updated

        self._tx.state.push_candidates[candidate.id] = candidate
        self._tx.state.push_candidate_by_cooldown_status[key] = candidate.id
        return candidate

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PushCandidate, ...]:
        candidates = [
            candidate
            for candidate in self._tx.state.push_candidates.values()
            if candidate.project_memory_space_id == project_memory_space_id
        ]
        candidates.sort(key=lambda candidate: (candidate.updated_at, candidate.id), reverse=True)
        return tuple(candidates[:limit])

    async def list_pending(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PushCandidate, ...]:
        candidates = [
            candidate
            for candidate in self._tx.state.push_candidates.values()
            if candidate.project_memory_space_id == project_memory_space_id
            and candidate.status == "pending"
        ]
        candidates.sort(key=lambda candidate: (-candidate.priority, candidate.created_at, candidate.id))
        return tuple(candidates[:limit])
