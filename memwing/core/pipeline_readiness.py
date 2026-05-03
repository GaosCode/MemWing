from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from memwing.core.scope import EffectiveScope


class PipelineReadinessProfile(StrEnum):
    MINIMAL_INGEST = "minimal-ingest"
    CONTEXT_ASSEMBLE = "context-assemble"
    RETRIEVAL_EVALUATE = "retrieval-evaluate"
    WRITE_EVALUATE = "write-evaluate"
    FULL_DERIVED = "full-derived"


class PipelineLane(StrEnum):
    SOURCE_EVENTS = "source_events"
    WORKING_MEMORY = "working_memory"
    EVIDENCE = "evidence"
    PAGE_MEMORY = "page_memory"
    MEMORY_ITEMS = "memory_items"
    GRAPH = "graph"


@dataclass(frozen=True, slots=True)
class PipelineReadinessCommand:
    source_event_ids: tuple[str, ...]
    scope: EffectiveScope
    profile: PipelineReadinessProfile

    def __post_init__(self) -> None:
        source_event_ids = tuple(dict.fromkeys(self.source_event_ids))
        if not source_event_ids:
            raise ValueError("pipeline readiness requires source_event_ids")
        object.__setattr__(self, "source_event_ids", source_event_ids)


@dataclass(frozen=True, slots=True)
class SourceEventReadiness:
    expected: int
    available: int
    missing_source_event_ids: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.available == self.expected and not self.missing_source_event_ids


@dataclass(frozen=True, slots=True)
class JobStatusCount:
    pending: int = 0
    processing_active: int = 0
    processing_stale: int = 0
    processing_invalid: int = 0
    dead_letter: int = 0
    succeeded: int = 0

    @property
    def incomplete(self) -> int:
        return (
            self.pending
            + self.processing_active
            + self.processing_stale
            + self.processing_invalid
        )

    @property
    def ready(self) -> bool:
        return self.incomplete == 0 and self.dead_letter == 0


@dataclass(frozen=True, slots=True)
class OutboxReadiness:
    pending: int
    processing_active: int
    processing_stale: int
    processing_invalid: int
    dead_letter: int
    by_job_type: dict[str, JobStatusCount]

    @property
    def ready(self) -> bool:
        return (
            self.pending == 0
            and self.processing_active == 0
            and self.processing_stale == 0
            and self.processing_invalid == 0
            and self.dead_letter == 0
        )


@dataclass(frozen=True, slots=True)
class DerivedLayerReadiness:
    ready: bool
    count: int = 0
    pending: int = 0
    reason: str | None = None
    matched_source_event_ids: tuple[str, ...] = ()
    unmatched_source_event_ids: tuple[str, ...] = ()
    page_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PipelineReadinessResult:
    ready: bool
    profile: PipelineReadinessProfile
    source_events: SourceEventReadiness
    outbox: OutboxReadiness
    derived: dict[str, DerivedLayerReadiness]
    warnings: tuple[str, ...]
    timed_out: bool = False
    trace_id: str | None = None
