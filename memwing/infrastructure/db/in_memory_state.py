from __future__ import annotations

from dataclasses import dataclass, field

from memwing.core.models import (
    AuditEvent,
    EvidenceChunk,
    GraphWriteJob,
    MemoryGraphLink,
    MemoryItem,
    MemoryPageVersion,
    MemoryVersion,
    OutboxJob,
    PageMemory,
    WorkingMemoryEntry,
    SourceEvent,
)
from memwing.core.scope import (
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)


@dataclass(slots=True)
class InMemoryState:
    source_events: dict[str, SourceEvent] = field(default_factory=dict)
    source_by_raw_hash: dict[tuple[str, str], str] = field(default_factory=dict)
    source_by_runtime_key: dict[tuple[str, str], str] = field(default_factory=dict)
    audit_events: dict[str, AuditEvent] = field(default_factory=dict)
    outbox_jobs: dict[str, OutboxJob] = field(default_factory=dict)
    outbox_by_idempotency_key: dict[str, str] = field(default_factory=dict)
    evidence_chunks: dict[str, EvidenceChunk] = field(default_factory=dict)
    evidence_by_source_chunk: dict[tuple[str, int], str] = field(default_factory=dict)
    working_memory_entries: dict[str, WorkingMemoryEntry] = field(default_factory=dict)
    working_memory_by_scope_sequence: dict[tuple[str, str | None, int], str] = field(default_factory=dict)
    memory_items: dict[str, MemoryItem] = field(default_factory=dict)
    memory_versions: dict[str, MemoryVersion] = field(default_factory=dict)
    memory_version_by_memory_version: dict[tuple[str, int], str] = field(default_factory=dict)
    memory_pages: dict[str, PageMemory] = field(default_factory=dict)
    memory_page_by_scope: dict[tuple[str, str, str], str] = field(default_factory=dict)
    memory_page_versions: dict[str, MemoryPageVersion] = field(default_factory=dict)
    memory_page_version_by_page_version: dict[tuple[str, int], str] = field(default_factory=dict)
    graph_write_jobs: dict[str, GraphWriteJob] = field(default_factory=dict)
    graph_job_by_idempotency_key: dict[str, str] = field(default_factory=dict)
    memory_graph_links: dict[str, MemoryGraphLink] = field(default_factory=dict)
    memory_graph_link_by_backend_object: dict[tuple[str, str, str, str, str], str] = field(default_factory=dict)
    projects: dict[str, ProjectMemorySpace] = field(default_factory=dict)
    runtime_bindings: list[RuntimeScopeBinding] = field(default_factory=list)
    platform_bindings: list[PlatformScopeBinding] = field(default_factory=list)
    group_settings: dict[tuple[str, str], GroupMemorySettings] = field(default_factory=dict)
