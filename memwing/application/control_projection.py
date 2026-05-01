from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from memwing.application.decay_service import DEFAULT_FORGETTING_REVIEW_THRESHOLD
from memwing.core.forgetting_curve import (
    compute_decayed_score,
    effective_last_touched_at,
    next_threshold_at,
)
from memwing.core.models import (
    GraphWriteJob,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    OutboxJob,
    PushCandidate,
    PushCandidateType,
    SourceEvent,
)


@dataclass(frozen=True, slots=True)
class ControlMemoryItemProjection:
    id: str
    title: str
    summary: str | None
    display_type: MemoryDisplayType
    route: MemoryRoute
    status: MemoryStatus
    group_id: str | None
    thread_id: str | None
    source_event_ids: tuple[str, ...]
    decay_score: float
    original_score: float
    half_life_days: int
    recall_threshold: float
    curve_state: str
    last_reinforced_at: datetime
    next_review_at: datetime | None
    retention_reason: str
    flags: tuple[str, ...]
    source_state: str
    graph_backend_raw_retained: bool
    available_actions: tuple[str, ...]
    warning_count: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ControlMemoryListProjection:
    items: tuple[ControlMemoryItemProjection, ...]
    next_cursor: str | None
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlGraphLinkProjection:
    id: str
    backend: str
    backend_object_type: str
    backend_object_id: str
    link_type: str


@dataclass(frozen=True, slots=True)
class ControlMemoryDetailProjection:
    item: ControlMemoryItemProjection
    content: str
    source_event_ids: tuple[str, ...]
    memory_item_ids: tuple[str, ...]
    graph_links: tuple[ControlGraphLinkProjection, ...]
    audit_refs: tuple[str, ...]
    trace_id: str


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
    trace_id: str


def project_memory_item(
    item: MemoryItem,
    *,
    source_events: tuple[SourceEvent, ...],
    graph_links: tuple[MemoryGraphLink, ...],
    now: datetime,
    recall_threshold: float = DEFAULT_FORGETTING_REVIEW_THRESHOLD,
) -> ControlMemoryItemProjection:
    last_reinforced_at = effective_last_touched_at(item)
    decay_score = compute_decayed_score(
        original_score=item.original_score,
        effective_last_touched_at=last_reinforced_at,
        now=now,
        half_life_days=item.half_life_days,
    )
    source_state = _source_state(source_events)
    graph_backend_raw_retained = any(event.graph_backend_raw_retained for event in source_events)
    curve_state = _curve_state(item, decay_score=decay_score, recall_threshold=recall_threshold)
    return ControlMemoryItemProjection(
        id=item.id,
        title=item.title,
        summary=item.summary,
        display_type=item.display_type,
        route=item.route,
        status=item.status,
        group_id=item.group_id,
        thread_id=item.thread_id,
        source_event_ids=item.source_event_ids,
        decay_score=decay_score,
        original_score=item.original_score,
        half_life_days=item.half_life_days,
        recall_threshold=recall_threshold,
        curve_state=curve_state,
        last_reinforced_at=last_reinforced_at,
        next_review_at=_next_review_at(
            item,
            decay_score=decay_score,
            last_reinforced_at=last_reinforced_at,
            now=now,
            recall_threshold=recall_threshold,
        ),
        retention_reason=_retention_reason(
            item,
            decay_score=decay_score,
            recall_threshold=recall_threshold,
        ),
        flags=_flags(
            item,
            decay_score=decay_score,
            recall_threshold=recall_threshold,
            graph_links=graph_links,
            source_state=source_state,
        ),
        source_state=source_state,
        graph_backend_raw_retained=graph_backend_raw_retained,
        available_actions=_available_actions(item),
        warning_count=_warning_count(source_state=source_state, curve_state=curve_state),
        updated_at=item.updated_at,
    )


def project_graph_link(link: MemoryGraphLink) -> ControlGraphLinkProjection:
    return ControlGraphLinkProjection(
        id=link.id,
        backend=link.backend,
        backend_object_type=link.backend_object_type,
        backend_object_id=link.backend_object_id,
        link_type=link.link_type,
    )


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


def _curve_state(item: MemoryItem, *, decay_score: float, recall_threshold: float) -> str:
    if item.status in (
        MemoryStatus.ARCHIVED,
        MemoryStatus.HIDDEN,
        MemoryStatus.INVALID,
        MemoryStatus.REMOVED,
    ):
        return item.status.value
    if item.pinned:
        return "pinned"
    if decay_score < recall_threshold:
        return "below_threshold"
    if decay_score < recall_threshold + 0.1:
        return "fading"
    return "retained"


def _next_review_at(
    item: MemoryItem,
    *,
    decay_score: float,
    last_reinforced_at: datetime,
    now: datetime,
    recall_threshold: float,
) -> datetime | None:
    if item.pinned or item.status in (MemoryStatus.REMOVED, MemoryStatus.INVALID):
        return None
    if decay_score < recall_threshold:
        return now
    return next_threshold_at(
        original_score=item.original_score,
        effective_last_touched_at=last_reinforced_at,
        now=now,
        half_life_days=item.half_life_days,
        threshold=recall_threshold,
    )


def _retention_reason(item: MemoryItem, *, decay_score: float, recall_threshold: float) -> str:
    if item.pinned:
        return "pinned_bypasses_decay"
    if item.status in (
        MemoryStatus.ARCHIVED,
        MemoryStatus.HIDDEN,
        MemoryStatus.INVALID,
        MemoryStatus.REMOVED,
    ):
        return f"lifecycle_{item.status.value}"
    if decay_score < recall_threshold:
        return "score_below_recall_threshold"
    return "score_above_recall_threshold"


def _flags(
    item: MemoryItem,
    *,
    decay_score: float,
    recall_threshold: float,
    graph_links: tuple[MemoryGraphLink, ...],
    source_state: str,
) -> tuple[str, ...]:
    flags: list[str] = []
    if item.pinned:
        flags.append("pinned")
    if item.status in (
        MemoryStatus.ARCHIVED,
        MemoryStatus.HIDDEN,
        MemoryStatus.INVALID,
        MemoryStatus.REMOVED,
    ):
        flags.append(item.status.value)
    if item.status is MemoryStatus.NEEDS_REVIEW or decay_score < recall_threshold:
        flags.append("needs_review")
    if graph_links:
        flags.append("graph_linked")
    if source_state == "redacted":
        flags.append("source_redacted")
    return tuple(flags)


def _source_state(source_events: tuple[SourceEvent, ...]) -> str:
    if not source_events:
        return "missing"
    if any(event.purged_at is not None or event.purge_level != "none" for event in source_events):
        return "redacted"
    return "available"


def _available_actions(item: MemoryItem) -> tuple[str, ...]:
    if item.status is MemoryStatus.REMOVED:
        return ()
    actions: list[str] = []
    if item.status in (MemoryStatus.CANDIDATE, MemoryStatus.ACTIVE, MemoryStatus.NEEDS_REVIEW):
        actions.append("confirm")
    if item.status is MemoryStatus.ARCHIVED:
        actions.append("unarchive")
    else:
        actions.append("archive")
    if item.status is MemoryStatus.HIDDEN:
        actions.append("unhide")
    else:
        actions.append("hide")
    actions.append("unpin" if item.pinned else "pin")
    return tuple(actions)


def _warning_count(*, source_state: str, curve_state: str) -> int:
    count = 0
    if source_state != "available":
        count += 1
    if curve_state == "below_threshold":
        count += 1
    return count


def _job_retryable(status: str, attempts: int, max_attempts: int) -> bool:
    return status in ("pending", "processing") and attempts < max_attempts
