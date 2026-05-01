from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from memwing.core.models import (
    AuditEvent,
    EvidenceChunk,
    ForgettingReviewCandidate,
    GraphWriteJob,
    MemoryGraphLink,
    MemoryItem,
    MemoryRecallEvent,
    MemoryPageVersion,
    MemoryVersion,
    OutboxJob,
    PageMemory,
    PageMemoryScopeType,
    PushCandidate,
    SourceEvent,
    WorkingMemoryEntry,
)
from memwing.core.runtime import RememberEventResult
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

    async def redact_source_event(
        self,
        *,
        source_event_id: str,
        redacted_content: str,
        purged_at: datetime,
        purged_by: str,
        purge_reason: str,
        purge_level: str,
        graph_backend_raw_retained: bool,
    ) -> SourceEvent | None:
        ...

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[SourceEvent, ...]:
        ...

    async def list_recent_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[SourceEvent, ...]:
        ...


class AuditEventRepositoryPort(Protocol):
    async def record(self, event: AuditEvent) -> AuditEvent:
        ...

    async def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
        limit: int,
    ) -> tuple[AuditEvent, ...]:
        ...

    async def get_by_idempotency_key(
        self,
        *,
        entity_type: str,
        entity_id: str,
        idempotency_key: str,
    ) -> AuditEvent | None:
        ...


class OutboxJobRepositoryPort(Protocol):
    async def enqueue(self, job: OutboxJob) -> OutboxJob:
        ...

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
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


class EvidenceChunkRepositoryPort(Protocol):
    async def upsert_chunk(self, chunk: EvidenceChunk) -> EvidenceChunk:
        ...

    async def mark_source_redacted(
        self,
        *,
        source_event_id: str,
        invalidated_at: datetime,
    ) -> int:
        ...


class WorkingMemoryRepositoryPort(Protocol):
    async def append(self, entry: WorkingMemoryEntry) -> WorkingMemoryEntry:
        ...

    async def list_recent(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        limit: int,
    ) -> tuple[WorkingMemoryEntry, ...]:
        ...

    async def next_sequence(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
    ) -> int:
        ...

    async def sum_unflushed_tokens(
        self,
        *,
        project_memory_space_id: str,
        group_id: str | None,
        thread_id: str | None,
    ) -> int:
        ...

    async def mark_flushed(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        through_sequence: int,
        flushed_at: datetime,
    ) -> int:
        ...


class MemoryRecallEventRepositoryPort(Protocol):
    async def record(self, event: MemoryRecallEvent) -> MemoryRecallEvent:
        ...


class MemoryItemRepositoryPort(Protocol):
    async def upsert(self, item: MemoryItem) -> MemoryItem:
        ...

    async def get(self, memory_id: str) -> MemoryItem | None:
        ...

    async def get_for_update(self, memory_id: str) -> MemoryItem | None:
        ...

    async def list_by_source_event(self, source_event_id: str) -> tuple[MemoryItem, ...]:
        ...

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[MemoryItem, ...]:
        ...

    async def list_decay_candidates(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[MemoryItem, ...]:
        ...


class MemoryVersionRepositoryPort(Protocol):
    async def record(self, version: MemoryVersion) -> MemoryVersion:
        ...

    async def get_latest(self, memory_id: str) -> MemoryVersion | None:
        ...

    async def get(self, memory_id: str, version: int) -> MemoryVersion | None:
        ...

    async def list_by_memory(
        self,
        *,
        memory_id: str,
        limit: int,
    ) -> tuple[MemoryVersion, ...]:
        ...


class MemoryPageRepositoryPort(Protocol):
    async def upsert(self, page: PageMemory) -> PageMemory:
        ...

    async def lock_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> None:
        ...

    async def get_by_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> PageMemory | None:
        ...

    async def get_by_scope_for_update(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> PageMemory | None:
        ...

    async def get(self, page_id: str) -> PageMemory | None:
        ...

    async def get_for_update(self, page_id: str) -> PageMemory | None:
        ...

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[PageMemory, ...]:
        ...

    async def mark_needs_rebuild_for_source(
        self,
        *,
        source_event_id: str,
        updated_at: datetime,
    ) -> int:
        ...

    async def list_needs_rebuild(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PageMemory, ...]:
        ...


class MemoryPageVersionRepositoryPort(Protocol):
    async def record(self, version: MemoryPageVersion) -> MemoryPageVersion:
        ...

    async def get(self, page_id: str, version: int) -> MemoryPageVersion | None:
        ...

    async def list_by_page(
        self,
        *,
        page_id: str,
        limit: int,
    ) -> tuple[MemoryPageVersion, ...]:
        ...


class GraphWriteJobRepositoryPort(Protocol):
    async def enqueue(self, job: GraphWriteJob) -> GraphWriteJob:
        ...

    async def list_for_project(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[GraphWriteJob, ...]:
        ...

    async def claim_pending(
        self,
        *,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
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
    ) -> tuple[PushCandidate, ...]:
        ...

    async def list_pending(
        self,
        *,
        project_memory_space_id: str,
        limit: int,
    ) -> tuple[PushCandidate, ...]:
        ...


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
