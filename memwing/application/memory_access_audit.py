from __future__ import annotations

import hashlib
from datetime import datetime
import uuid

from memwing.core.memory_access import MemoryAccessSearchResult
from memwing.core.models import MemoryRecallEvent
from memwing.ports.event_store import EventStoreUnitOfWorkPort


async def record_recall_events(
    unit_of_work: EventStoreUnitOfWorkPort,
    *,
    result: MemoryAccessSearchResult,
    query_text: str,
    project_memory_space_id: str,
    trace_id: str,
    now: datetime,
) -> None:
    query_hash = _query_hash(query_text)
    async with unit_of_work.transaction() as tx:
        for rank, item in enumerate(result.results, start=1):
            memory_ids = item.memory_item_ids or (
                (item.id,) if item.source == "memory_item" else ()
            )
            for memory_id in memory_ids:
                await tx.memory_recall_events.record(
                    MemoryRecallEvent(
                        id=str(uuid.uuid4()),
                        project_memory_space_id=project_memory_space_id,
                        memory_id=memory_id,
                        source=item.source,
                        query_hash=query_hash,
                        trace_id=trace_id,
                        recalled_at=now,
                        rank=rank,
                        score=item.score,
                        created_at=now,
                    )
                )


def trace_id(operation: str, agent_id: str) -> str:
    return f"memory_access:{operation}:{agent_id}"


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.strip().casefold().encode("utf-8")).hexdigest()
