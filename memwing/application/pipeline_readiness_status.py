from __future__ import annotations

from memwing.core.pipeline_readiness import (
    DerivedLayerReadiness,
    JobStatusCount,
    PipelineLane,
    PipelineReadinessProfile,
    SourceEventReadiness,
)


EVIDENCE_INDEX_JOB_TYPE = "evidence.index_source_event"
WORKING_MEMORY_APPEND_JOB_TYPE = "working_memory.append"
PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE = "page_memory.maybe_rebuild"
LONG_TERM_FILTER_CLASSIFY_JOB_TYPE = "long_term_filter.classify"


def build_derived_readiness(
    *,
    source_readiness: SourceEventReadiness,
    outbox_by_type: dict[str, JobStatusCount],
    evidence_enabled: bool,
    graph_enabled: bool,
    evidence_count: int,
    working_count: int,
    page_count: int,
    page_ids: tuple[str, ...],
    page_matched_source_event_ids: tuple[str, ...],
    page_unmatched_source_event_ids: tuple[str, ...],
    memory_item_count: int,
    graph_status: JobStatusCount,
) -> dict[str, DerivedLayerReadiness]:
    return {
        PipelineLane.WORKING_MEMORY.value: _layer(
            ready=(
                source_readiness.ready
                and working_count >= source_readiness.available
                and _job_type_ready(outbox_by_type, WORKING_MEMORY_APPEND_JOB_TYPE)
            ),
            count=working_count,
            reason=_reason_for_event_layer(
                expected=source_readiness.available,
                count=working_count,
                job_status=outbox_by_type.get(WORKING_MEMORY_APPEND_JOB_TYPE),
                empty_reason="working_memory_pending",
            ),
        ),
        PipelineLane.EVIDENCE.value: _configured_event_layer(
            enabled=evidence_enabled,
            expected=source_readiness.available,
            count=evidence_count,
            job_status=outbox_by_type.get(EVIDENCE_INDEX_JOB_TYPE),
            disabled_reason="evidence_disabled",
            empty_reason="evidence_empty",
        ),
        PipelineLane.PAGE_MEMORY.value: _scope_layer(
            count=page_count,
            job_status=outbox_by_type.get(PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE),
            empty_reason="page_memory_empty",
            matched_source_event_ids=page_matched_source_event_ids,
            unmatched_source_event_ids=page_unmatched_source_event_ids,
            page_ids=page_ids,
        ),
        PipelineLane.MEMORY_ITEMS.value: _scope_layer(
            count=memory_item_count,
            job_status=outbox_by_type.get(LONG_TERM_FILTER_CLASSIFY_JOB_TYPE),
            empty_reason="memory_items_empty",
        ),
        PipelineLane.GRAPH.value: _graph_layer(
            enabled=graph_enabled,
            graph_status=graph_status,
        ),
    }

def warnings_for_readiness(
    *,
    derived: dict[str, DerivedLayerReadiness],
    outbox_by_type: dict[str, JobStatusCount],
    evidence_enabled: bool,
    graph_enabled: bool,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not evidence_enabled:
        warnings.append("evidence_disabled")
    if not graph_enabled:
        warnings.append("graph_disabled")
    for job_type, status in outbox_by_type.items():
        if status.dead_letter:
            warnings.append(f"{job_type}:dead_letter")
        if status.processing_invalid:
            warnings.append(f"{job_type}:processing_invalid")
    for lane, status in derived.items():
        if not status.ready and status.reason in {"evidence_disabled", "graph_disabled"}:
            continue
        if not status.ready and status.reason is not None:
            warnings.append(f"{lane}:{status.reason}")
    return tuple(dict.fromkeys(warnings))


def profile_ready(
    *,
    profile: PipelineReadinessProfile,
    source_events: SourceEventReadiness,
    derived: dict[str, DerivedLayerReadiness],
) -> bool:
    if not source_events.ready:
        return False
    if profile == PipelineReadinessProfile.MINIMAL_INGEST:
        return True
    if profile == PipelineReadinessProfile.CONTEXT_ASSEMBLE:
        return derived[PipelineLane.WORKING_MEMORY.value].ready
    if profile == PipelineReadinessProfile.RETRIEVAL_EVALUATE:
        return any(
            derived[lane.value].ready
            for lane in (
                PipelineLane.EVIDENCE,
                PipelineLane.GRAPH,
                PipelineLane.MEMORY_ITEMS,
            )
        )
    if profile == PipelineReadinessProfile.WRITE_EVALUATE:
        return (
            derived[PipelineLane.PAGE_MEMORY.value].ready
            and derived[PipelineLane.MEMORY_ITEMS.value].ready
        )
    if profile == PipelineReadinessProfile.FULL_DERIVED:
        required = (
            PipelineLane.WORKING_MEMORY,
            PipelineLane.PAGE_MEMORY,
            PipelineLane.MEMORY_ITEMS,
        )
        configured_optional = (
            lane
            for lane in (PipelineLane.EVIDENCE, PipelineLane.GRAPH)
            if derived[lane.value].reason not in {"evidence_disabled", "graph_disabled"}
        )
        return all(derived[lane.value].ready for lane in (*required, *configured_optional))
    raise ValueError(f"unsupported pipeline readiness profile: {profile}")


def profile_terminally_blocked(
    *,
    profile: PipelineReadinessProfile,
    derived: dict[str, DerivedLayerReadiness],
) -> bool:
    if profile == PipelineReadinessProfile.MINIMAL_INGEST:
        return False
    if profile == PipelineReadinessProfile.CONTEXT_ASSEMBLE:
        return _lane_dead_letter(derived, PipelineLane.WORKING_MEMORY)
    if profile == PipelineReadinessProfile.WRITE_EVALUATE:
        return any(
            _lane_dead_letter(derived, lane)
            for lane in (PipelineLane.PAGE_MEMORY, PipelineLane.MEMORY_ITEMS)
        )
    if profile == PipelineReadinessProfile.FULL_DERIVED:
        required = (
            PipelineLane.WORKING_MEMORY,
            PipelineLane.PAGE_MEMORY,
            PipelineLane.MEMORY_ITEMS,
            PipelineLane.EVIDENCE,
            PipelineLane.GRAPH,
        )
        return any(_lane_dead_letter(derived, lane) for lane in required)
    if profile == PipelineReadinessProfile.RETRIEVAL_EVALUATE:
        candidate_lanes = (
            PipelineLane.EVIDENCE,
            PipelineLane.GRAPH,
            PipelineLane.MEMORY_ITEMS,
        )
        return all(
            derived[lane.value].reason in {"dead_letter", "evidence_disabled", "graph_disabled"}
            for lane in candidate_lanes
        )
    raise ValueError(f"unsupported pipeline readiness profile: {profile}")


def _lane_dead_letter(
    derived: dict[str, DerivedLayerReadiness],
    lane: PipelineLane,
) -> bool:
    return derived[lane.value].reason == "dead_letter"


def _job_type_ready(by_job_type: dict[str, JobStatusCount], job_type: str) -> bool:
    status = by_job_type.get(job_type)
    return status is not None and status.ready


def _configured_event_layer(
    *,
    enabled: bool,
    expected: int,
    count: int,
    job_status: JobStatusCount | None,
    disabled_reason: str,
    empty_reason: str,
) -> DerivedLayerReadiness:
    if not enabled:
        return _layer(ready=False, count=0, reason=disabled_reason)
    return _layer(
        ready=expected > 0 and count >= expected and (job_status is not None and job_status.ready),
        count=count,
        reason=_reason_for_event_layer(
            expected=expected,
            count=count,
            job_status=job_status,
            empty_reason=empty_reason,
        ),
    )


def _scope_layer(
    *,
    count: int,
    job_status: JobStatusCount | None,
    empty_reason: str,
    matched_source_event_ids: tuple[str, ...] = (),
    unmatched_source_event_ids: tuple[str, ...] = (),
    page_ids: tuple[str, ...] = (),
) -> DerivedLayerReadiness:
    return _layer(
        ready=count > 0 and (job_status is not None and job_status.ready),
        count=count,
        reason=_reason_for_scope_layer(
            count=count,
            job_status=job_status,
            empty_reason=empty_reason,
        ),
        matched_source_event_ids=matched_source_event_ids,
        unmatched_source_event_ids=unmatched_source_event_ids,
        page_ids=page_ids,
    )


def _graph_layer(
    *,
    enabled: bool,
    graph_status: JobStatusCount,
) -> DerivedLayerReadiness:
    if not enabled:
        return _layer(ready=False, count=0, reason="graph_disabled")
    return _layer(
        ready=graph_status.ready and graph_status.succeeded > 0,
        count=graph_status.succeeded,
        pending=graph_status.incomplete,
        reason=_reason_for_scope_layer(
            count=graph_status.succeeded,
            job_status=graph_status,
            empty_reason="graph_empty",
        ),
    )


def _layer(
    *,
    ready: bool,
    count: int,
    pending: int = 0,
    reason: str | None = None,
    matched_source_event_ids: tuple[str, ...] = (),
    unmatched_source_event_ids: tuple[str, ...] = (),
    page_ids: tuple[str, ...] = (),
) -> DerivedLayerReadiness:
    return DerivedLayerReadiness(
        ready=ready,
        count=count,
        pending=pending,
        reason=None if ready else reason,
        matched_source_event_ids=matched_source_event_ids,
        unmatched_source_event_ids=unmatched_source_event_ids,
        page_ids=page_ids,
    )


def _reason_for_event_layer(
    *,
    expected: int,
    count: int,
    job_status: JobStatusCount | None,
    empty_reason: str,
) -> str | None:
    job_reason = _reason_for_job_status(job_status)
    if job_reason is not None:
        return job_reason
    if count < expected:
        return empty_reason
    return None


def _reason_for_scope_layer(
    *,
    count: int,
    job_status: JobStatusCount | None,
    empty_reason: str,
) -> str | None:
    job_reason = _reason_for_job_status(job_status)
    if job_reason is not None:
        return job_reason
    if count <= 0:
        return empty_reason
    return None


def _reason_for_job_status(job_status: JobStatusCount | None) -> str | None:
    if job_status is None:
        return "job_missing"
    if job_status.dead_letter:
        return "dead_letter"
    if job_status.processing_invalid:
        return "processing_invalid"
    if job_status.processing_active:
        return "processing_active"
    if job_status.processing_stale:
        return "processing_stale"
    if job_status.pending:
        return "pending"
    return None
