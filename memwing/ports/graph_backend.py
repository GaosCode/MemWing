from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from memwing.core.models import (
    GraphWriteJob,
    GraphWriteResult,
    MemoryItem,
    SourceEvent,
)
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult
from memwing.core.scope import EffectiveScope


@dataclass(frozen=True, slots=True)
class GraphWriteRequest:
    job: GraphWriteJob
    memory_item: MemoryItem
    source_events: tuple[SourceEvent, ...]


@dataclass(frozen=True, slots=True)
class GraphWriteBatchRequest:
    requests: tuple[GraphWriteRequest, ...]


@dataclass(frozen=True, slots=True)
class GraphWriteBatchItemResult:
    job_id: str
    result: GraphWriteResult | None
    error_type: str | None
    error_message: str | None
    reason_code: str | None
    retryable: bool


@dataclass(frozen=True, slots=True)
class GraphWriteBatchResult:
    items: tuple[GraphWriteBatchItemResult, ...]


@dataclass(frozen=True, slots=True)
class GraphFactPreseedRequest:
    memory_items: tuple[MemoryItem, ...]
    source_events: tuple[SourceEvent, ...]


@dataclass(frozen=True, slots=True)
class GraphFactPreseedItemResult:
    memory_id: str
    result: GraphWriteResult | None
    error_type: str | None
    error_message: str | None
    reason_code: str | None
    retryable: bool


@dataclass(frozen=True, slots=True)
class GraphFactPreseedResult:
    items: tuple[GraphFactPreseedItemResult, ...]


@runtime_checkable
class GraphBackendPort(Protocol):
    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        ...

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        ...

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        ...

    async def ingest_graph_jobs(self, request: GraphWriteBatchRequest) -> GraphWriteBatchResult:
        ...

    async def preseed_facts(self, request: GraphFactPreseedRequest) -> GraphFactPreseedResult:
        ...

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        ...
