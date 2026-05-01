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
    MemoryPageVersion,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    OutboxJob,
    PageMemory,
    PageMemoryTopic,
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
class ControlMemoryVersionProjection:
    id: str
    memory_id: str
    version: int
    title: str
    summary: str | None
    status: MemoryStatus
    source_event_ids: tuple[str, ...]
    changed_by: str
    change_reason: str
    created_at: datetime


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
class ControlPageTopicProjection:
    title: str
    summary: str
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ControlPageProjection:
    id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None
    scope_type: str
    scope_id: str
    title: str
    brief: str
    topics: tuple[ControlPageTopicProjection, ...]
    open_questions: tuple[str, ...]
    next_steps: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]
    version: int
    needs_rebuild: bool
    graph_backend_raw_retained: bool
    warning_count: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ControlPageListProjection:
    items: tuple[ControlPageProjection, ...]
    next_cursor: str | None
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlPageDetailProjection:
    page: ControlPageProjection
    versions: tuple["ControlPageVersionProjection", ...]
    audit_refs: tuple[str, ...]
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlPageVersionProjection:
    id: str
    page_id: str
    version: int
    title: str
    brief: str
    topics: tuple[ControlPageTopicProjection, ...]
    open_questions: tuple[str, ...]
    next_steps: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]
    changed_by: str
    change_reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ControlSourceEventProjection:
    id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    source_type: str
    content_preview: str
    source_url: str | None
    purged: bool
    purge_level: str
    graph_backend_raw_retained: bool
    event_time: datetime
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ControlSourceEventListProjection:
    items: tuple[ControlSourceEventProjection, ...]
    next_cursor: str | None
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlSourceEventDetailProjection:
    source_event: ControlSourceEventProjection
    memory_item_ids: tuple[str, ...]
    audit_refs: tuple[str, ...]
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlMaintenanceProjection:
    forgetting_review_count: int
    pending_push_count: int
    job_count: int
    warning_count: int
    jobs: tuple[ControlJobProjection, ...]
    push_candidates: tuple[ControlPushCandidateProjection, ...]
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


@dataclass(frozen=True, slots=True)
class ControlSettingsProjection:
    project_memory_space_id: str
    safe_mode_enabled: bool
    shared_group_id: str | None
    settings_mutation_supported: bool
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlIntegrationProjection:
    name: str
    configured: bool
    writable: bool


@dataclass(frozen=True, slots=True)
class ControlIntegrationsProjection:
    items: tuple[ControlIntegrationProjection, ...]
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


def project_memory_version(version) -> ControlMemoryVersionProjection:
    return ControlMemoryVersionProjection(
        id=version.id,
        memory_id=version.memory_id,
        version=version.version,
        title=version.title,
        summary=version.summary,
        status=version.status,
        source_event_ids=version.source_event_ids,
        changed_by=version.changed_by,
        change_reason=version.change_reason,
        created_at=version.created_at,
    )


def project_page(
    page: PageMemory,
    *,
    source_events: tuple[SourceEvent, ...],
) -> ControlPageProjection:
    graph_backend_raw_retained = any(event.graph_backend_raw_retained for event in source_events)
    source_redacted = any(event.purged_at is not None or event.purge_level != "none" for event in source_events)
    warning_count = int(page.needs_rebuild) + int(source_redacted) + int(graph_backend_raw_retained)
    return ControlPageProjection(
        id=page.id,
        project_memory_space_id=page.project_memory_space_id,
        group_id=page.group_id,
        thread_id=page.thread_id,
        shared_group_id=page.shared_group_id,
        scope_type=page.scope_type,
        scope_id=page.scope_id,
        title=page.title,
        brief=page.brief,
        topics=tuple(project_page_topic(topic) for topic in page.topics),
        open_questions=page.open_questions,
        next_steps=page.next_steps,
        source_event_ids=page.source_event_ids,
        linked_memory_item_ids=page.linked_memory_item_ids,
        version=page.version,
        needs_rebuild=page.needs_rebuild,
        graph_backend_raw_retained=graph_backend_raw_retained,
        warning_count=warning_count,
        updated_at=page.updated_at,
    )


def project_page_topic(topic: PageMemoryTopic) -> ControlPageTopicProjection:
    return ControlPageTopicProjection(
        title=topic.title,
        summary=topic.summary,
        source_event_ids=topic.source_event_ids,
        linked_memory_item_ids=topic.linked_memory_item_ids,
    )


def project_page_version(version: MemoryPageVersion) -> ControlPageVersionProjection:
    return ControlPageVersionProjection(
        id=version.id,
        page_id=version.page_id,
        version=version.version,
        title=version.title,
        brief=version.brief,
        topics=tuple(project_page_topic(topic) for topic in version.topics),
        open_questions=version.open_questions,
        next_steps=version.next_steps,
        source_event_ids=version.source_event_ids,
        linked_memory_item_ids=version.linked_memory_item_ids,
        changed_by=version.changed_by,
        change_reason=version.change_reason,
        created_at=version.created_at,
    )


def project_source_event(event: SourceEvent) -> ControlSourceEventProjection:
    purged = event.purged_at is not None or event.purge_level != "none"
    return ControlSourceEventProjection(
        id=event.id,
        project_memory_space_id=event.project_memory_space_id,
        group_id=event.group_id,
        thread_id=event.thread_id,
        source_type=event.source_type,
        content_preview=event.content_preview,
        source_url=event.source_url,
        purged=purged,
        purge_level=event.purge_level,
        graph_backend_raw_retained=event.graph_backend_raw_retained,
        event_time=event.event_time,
        created_at=event.created_at,
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
