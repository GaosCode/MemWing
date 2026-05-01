from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
import uuid

from memwing.core.models import MemoryDisplayType, MemoryItem, MemoryStatus, PushCandidate
from memwing.ports.event_store import EventStoreUnitOfWorkPort


_DECISION_CARD_PRIORITY: Final = 100


@dataclass(frozen=True, slots=True)
class DecisionCardCommand:
    memory_id: str
    now: datetime
    trigger_reason: str
    trace_id: str = "decision_card:create"


class DecisionCardService:
    def __init__(self, unit_of_work: EventStoreUnitOfWorkPort) -> None:
        self._unit_of_work = unit_of_work

    async def create_for_memory(self, command: DecisionCardCommand) -> PushCandidate:
        async with self._unit_of_work.transaction() as tx:
            memory_item = await tx.memory_items.get(command.memory_id)
            if memory_item is None:
                raise ValueError(f"memory item {command.memory_id} was not found")
            _validate_decision_card_memory(memory_item)
            candidate = await tx.push_candidates.upsert(
                _decision_card_candidate(memory_item, command=command)
            )
            return candidate


def _validate_decision_card_memory(memory_item: MemoryItem) -> None:
    if memory_item.status is not MemoryStatus.ACTIVE:
        raise ValueError("decision cards require an active memory item")
    if memory_item.display_type is not MemoryDisplayType.DECISION:
        raise ValueError("decision cards require a decision memory item")


def _decision_card_candidate(
    memory_item: MemoryItem,
    *,
    command: DecisionCardCommand,
) -> PushCandidate:
    cooldown_key = f"decision_card:{memory_item.project_memory_space_id}:{memory_item.id}"
    return PushCandidate(
        id=_uuid("push_candidate", cooldown_key),
        project_memory_space_id=memory_item.project_memory_space_id,
        group_id=memory_item.group_id,
        thread_id=memory_item.thread_id,
        shared_group_id=memory_item.shared_group_id,
        type="decision_card",
        title=memory_item.title,
        content=memory_item.content,
        memory_item_ids=(memory_item.id,),
        source_event_ids=memory_item.source_event_ids,
        trigger_reason=command.trigger_reason,
        trigger_source="memory_item",
        priority=_DECISION_CARD_PRIORITY,
        expires_at=None,
        status="pending",
        cooldown_key=cooldown_key,
        created_at=command.now,
        updated_at=command.now,
    )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
