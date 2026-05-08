from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from memwing.application.control_projection.memory import ControlMemoryItemProjection
from memwing.core.models import GraphWriteJob, OutboxJob, PushCandidate, PushCandidateType


@dataclass(frozen=True, slots=True)
class ControlForgettingReviewItemProjection:
    id: str
    memory: ControlMemoryItemProjection
    threshold: float
    reason: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ControlForgettingReviewProjection:
    items: tuple[ControlForgettingReviewItemProjection, ...]
    next_cursor: str | None
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlJobProjection:
    id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    next_run_at: datetime
    last_error: str | None
    dead_letter_reason: str | None
    retryable: bool


@dataclass(frozen=True, slots=True)
class ControlPushCandidateProjection:
    id: str
    type: PushCandidateType
    title: str
    status: str
    priority: int
    memory_item_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    trigger_reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ControlMaintenanceProjection:
    forgetting_review_count: int
    pending_push_count: int
    job_count: int
    warning_count: int
    jobs: tuple[ControlJobProjection, ...]
    push_candidates: tuple[ControlPushCandidateProjection, ...]
    jobs_next_cursor: str | None
    push_candidates_next_cursor: str | None
    next_cursor: str | None
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlSummaryProjection:
    pending_memory_count: int
    forgetting_review_count: int
    pending_push_count: int
    dead_letter_job_count: int
    warning_count: int
    trace_id: str


def project_graph_job(job: GraphWriteJob) -> ControlJobProjection:
    return ControlJobProjection(
        id=job.id,
        kind="graph_write",
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        next_run_at=job.next_run_at,
        last_error=job.last_error,
        dead_letter_reason=job.dead_letter_reason,
        retryable=_job_retryable(job.status, job.attempts, job.max_attempts),
    )


def project_outbox_job(job: OutboxJob) -> ControlJobProjection:
    return ControlJobProjection(
        id=job.id,
        kind="outbox",
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        next_run_at=job.next_run_at,
        last_error=job.last_error,
        dead_letter_reason=job.dead_letter_reason,
        retryable=_job_retryable(job.status, job.attempts, job.max_attempts),
    )


def project_push_candidate(candidate: PushCandidate) -> ControlPushCandidateProjection:
    return ControlPushCandidateProjection(
        id=candidate.id,
        type=candidate.type,
        title=candidate.title,
        status=candidate.status,
        priority=candidate.priority,
        memory_item_ids=candidate.memory_item_ids,
        source_event_ids=candidate.source_event_ids,
        trigger_reason=candidate.trigger_reason,
        created_at=candidate.created_at,
    )


def _job_retryable(status: str, attempts: int, max_attempts: int) -> bool:
    return status in ("pending", "processing") and attempts < max_attempts
