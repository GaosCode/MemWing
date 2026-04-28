from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass
from datetime import datetime
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
GraphWriteJobStatus = Literal["pending", "processing", "succeeded", "retry", "dead_letter"]


@dataclass(frozen=True, slots=True)
class SourceEvent:
    id: str
    project_memory_space_id: str
    group_id: str
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
