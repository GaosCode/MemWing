from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class MemoryRoute(StrEnum):
    GRAPH = "graph"
    VECTOR_ONLY = "vector_only"
    RAW_ONLY = "raw_only"
    MANUAL = "manual"


class MemoryDisplayType(StrEnum):
    DECISION = "decision"
    TASK = "task"
    PREFERENCE = "preference"
    RULE = "rule"
    NOTE = "note"
    EVIDENCE = "evidence"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    FADING = "fading"
    ARCHIVED = "archived"
    HIDDEN = "hidden"
    INVALID = "invalid"
    NEEDS_REVIEW = "needs_review"
    REMOVED = "removed"


PurgeLevel = Literal["none", "memwing_redaction"]
MemoryCreatedBy = Literal["system", "user", "agent"]
MemoryChangedBy = Literal["system", "user", "agent"]
PageMemoryScopeType = Literal["project", "group", "thread", "meeting"]
MemoryGraphLinkType = Literal["fact", "episode", "entity", "redaction_marker"]
GraphWriteJobStatus = Literal["pending", "processing", "succeeded", "retry", "dead_letter"]
OutboxJobStatus = Literal["pending", "processing", "succeeded", "dead_letter"]


@dataclass(frozen=True, slots=True)
class SourceEvent:
    id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None
    author_id: str | None
    author_name: str | None
    source_type: str
    content: str
    content_preview: str
    source_url: str | None
    event_time: datetime
    raw_payload_hash: str
    metadata: dict[str, object]
    purged_at: datetime | None
    purged_by: str | None
    purge_reason: str | None
    purge_level: PurgeLevel
    graph_backend_raw_retained: bool
    created_at: datetime
    runtime_event_idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    trace_id: str
    entity_type: str
    entity_id: str
    stage: str
    input_ref: str | None
    output_ref: str | None
    decision: str
    reason_code: str | None
    reason_text: str | None
    source_event_ids: tuple[str, ...]
    latency_ms: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OutboxJob:
    id: str
    project_memory_space_id: str
    source_event_id: str
    job_type: str
    payload_json: dict[str, object]
    status: OutboxJobStatus
    idempotency_key: str
    aggregate_key: str | None
    attempts: int
    max_attempts: int
    priority: int
    next_run_at: datetime
    locked_at: datetime | None
    locked_by: str | None
    lock_expires_at: datetime | None
    last_error: str | None
    dead_letter_reason: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    id: str
    source_event_id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None
    chunk_text: str
    chunk_index: int
    embedding_model: str | None
    embedding_ref: str | None
    embedding_vector: tuple[float, ...] | None
    invalidated_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkingMemoryEntry:
    id: str
    source_event_id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None
    content: str
    token_count: int
    sequence: int
    flushed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryItem:
    id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None
    route: MemoryRoute
    display_type: MemoryDisplayType
    title: str
    content: str
    summary: str | None
    source_event_ids: tuple[str, ...]
    primary_source_event_id: str | None
    status: MemoryStatus
    event_time: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    original_score: float
    half_life_days: int
    last_reviewed_at: datetime | None
    last_confirmed_at: datetime | None
    last_recalled_at: datetime | None
    recall_count: int
    cached_decayed_score: float | None
    last_decay_computed_at: datetime | None
    pinned: bool
    created_by: MemoryCreatedBy
    created_at: datetime
    activated_at: datetime | None
    updated_at: datetime
    archived_at: datetime | None
    hidden_at: datetime | None
    invalidated_at: datetime | None
    removed_at: datetime | None


@dataclass(frozen=True, slots=True)
class MemoryVersion:
    id: str
    memory_id: str
    version: int
    title: str
    content: str
    summary: str | None
    status: MemoryStatus
    source_event_ids: tuple[str, ...]
    changed_by: MemoryChangedBy
    change_reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PageMemory:
    id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None
    scope_type: PageMemoryScopeType
    scope_id: str
    title: str
    brief: str
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]
    version: int
    needs_rebuild: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryPageVersion:
    id: str
    page_id: str
    version: int
    title: str
    brief: str
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]
    changed_by: MemoryChangedBy
    change_reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LongTermFilterItem:
    title: str
    content: str
    route: MemoryRoute
    display_type: MemoryDisplayType
    original_score: float
    half_life_days: int
    source_event_ids: tuple[str, ...]
    primary_source_event_id: str | None
    reason: str
    confidence: float
    event_time: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class GraphBackendCapabilities:
    supports_temporal_facts: bool
    supports_fact_invalidation: bool
    supports_episode_provenance: bool
    supports_current_search: bool
    supports_history_search: bool
    supports_source_redaction_marker: bool


@dataclass(frozen=True, slots=True)
class GraphFact:
    backend: str
    fact_id: str
    fact_text: str
    source_event_ids: tuple[str, ...]
    valid_from: datetime | None
    valid_to: datetime | None
    invalidated_at: datetime | None
    confidence: float | None
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class GraphWriteResult:
    backend: str
    facts: tuple[GraphFact, ...]
    invalidated_facts: tuple[GraphFact, ...]
    backend_episode_refs: tuple[str, ...]
    backend_fact_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryGraphLink:
    id: str
    backend: str
    memory_id: str
    source_event_id: str
    project_memory_space_id: str
    backend_space_id: str
    backend_object_type: str
    backend_object_id: str
    link_type: MemoryGraphLinkType
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GraphWriteJob:
    id: str
    backend: str
    project_memory_space_id: str
    thread_id: str | None
    saga_id: str | None
    source_event_ids: tuple[str, ...]
    route: MemoryRoute
    status: GraphWriteJobStatus
    idempotency_key: str
    attempts: int
    max_attempts: int
    priority: int
    next_run_at: datetime
    dead_letter_reason: str | None
    last_error: str | None
    locked_at: datetime | None
    locked_by: str | None
    lock_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
