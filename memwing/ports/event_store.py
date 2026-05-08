from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from memwing.core.models import SourceEvent
from memwing.core.runtime import RememberEventResult
from memwing.core.scope import EffectiveScope
from memwing.ports.audit_events import AuditEventRepositoryPort
from memwing.ports.control_plane import (
    ForgettingReviewCandidateRepositoryPort,
    PushCandidateRepositoryPort,
)
from memwing.ports.derived_memory import (
    EvidenceChunkRepositoryPort,
    MemoryItemRepositoryPort,
    MemoryPageRepositoryPort,
    MemoryPageVersionRepositoryPort,
    MemoryRecallEventRepositoryPort,
    MemoryVersionRepositoryPort,
    WorkingMemoryRepositoryPort,
)
from memwing.ports.graph_jobs import (
    GraphWriteJobRepositoryPort,
    MemoryGraphLinkRepositoryPort,
)
from memwing.ports.model_result_cache import ModelResultCachePort
from memwing.ports.outbox_jobs import (
    EventStoreError,
    OutboxJobRepositoryPort,
    OutboxLockOwnershipError,
)
from memwing.ports.scope_bindings import ScopeBindingStorePort
from memwing.ports.source_events import SourceEventRepositoryPort


class EventStoreTransactionPort(Protocol):
    source_events: SourceEventRepositoryPort
    audit_events: AuditEventRepositoryPort
    outbox_jobs: OutboxJobRepositoryPort
    evidence_chunks: EvidenceChunkRepositoryPort
    working_memory_entries: WorkingMemoryRepositoryPort
    memory_recall_events: MemoryRecallEventRepositoryPort
    memory_items: MemoryItemRepositoryPort
    memory_versions: MemoryVersionRepositoryPort
    memory_pages: MemoryPageRepositoryPort
    memory_page_versions: MemoryPageVersionRepositoryPort
    graph_write_jobs: GraphWriteJobRepositoryPort
    memory_graph_links: MemoryGraphLinkRepositoryPort
    forgetting_review_candidates: ForgettingReviewCandidateRepositoryPort
    push_candidates: PushCandidateRepositoryPort
    model_result_cache: ModelResultCachePort


class EventStoreUnitOfWorkPort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[EventStoreTransactionPort]:
        ...


@runtime_checkable
class EventStorePort(Protocol):
    async def remember_event(self, event: SourceEvent) -> RememberEventResult:
        ...

    async def get_source_event(
        self, source_event_id: str, scope: EffectiveScope
    ) -> SourceEvent | None:
        ...


__all__ = (
    "AuditEventRepositoryPort",
    "EventStoreError",
    "EventStorePort",
    "EventStoreTransactionPort",
    "EventStoreUnitOfWorkPort",
    "EvidenceChunkRepositoryPort",
    "ForgettingReviewCandidateRepositoryPort",
    "GraphWriteJobRepositoryPort",
    "MemoryGraphLinkRepositoryPort",
    "MemoryItemRepositoryPort",
    "MemoryPageRepositoryPort",
    "MemoryPageVersionRepositoryPort",
    "MemoryRecallEventRepositoryPort",
    "MemoryVersionRepositoryPort",
    "OutboxJobRepositoryPort",
    "OutboxLockOwnershipError",
    "PushCandidateRepositoryPort",
    "ScopeBindingStorePort",
    "SourceEventRepositoryPort",
    "WorkingMemoryRepositoryPort",
)
