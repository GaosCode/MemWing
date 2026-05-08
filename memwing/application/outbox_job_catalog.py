from __future__ import annotations

from dataclasses import dataclass

from memwing.application.page_memory_trigger import (
    page_memory_target_from_source_event,
    page_memory_trigger_key_for_scope,
)
from memwing.core.models import SourceEvent
from memwing.core.pipeline_readiness import PipelineLane
from memwing.core.scope import EffectiveScope


EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE = "evidence.index_source_event"
WORKING_MEMORY_APPEND_JOB_TYPE = "working_memory.append"
PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE = "page_memory.maybe_rebuild"
LONG_TERM_FILTER_CLASSIFY_JOB_TYPE = "long_term_filter.classify"
PUSH_CANDIDATE_TRIGGER_JOB_TYPE = "push_candidate.trigger"
PUSH_CANDIDATE_SEND_JOB_TYPE = "push_candidate.send"

DEFAULT_SOURCE_EVENT_JOB_TYPES: tuple[str, ...] = (
    EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,
    WORKING_MEMORY_APPEND_JOB_TYPE,
    PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
    LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
)


@dataclass(frozen=True, slots=True)
class OutboxJobDefinition:
    job_type: str
    derived_layer: PipelineLane | None
    source_event_derived: bool


@dataclass(frozen=True, slots=True)
class OutboxJobCreation:
    job_type: str
    aggregate_key: str


@dataclass(frozen=True, slots=True)
class OutboxJobCreationPlan:
    jobs: tuple[OutboxJobCreation, ...]

    @property
    def job_types(self) -> tuple[str, ...]:
        return tuple(job.job_type for job in self.jobs)


_JOB_DEFINITIONS: dict[str, OutboxJobDefinition] = {
    EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE: OutboxJobDefinition(
        job_type=EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,
        derived_layer=PipelineLane.EVIDENCE,
        source_event_derived=True,
    ),
    WORKING_MEMORY_APPEND_JOB_TYPE: OutboxJobDefinition(
        job_type=WORKING_MEMORY_APPEND_JOB_TYPE,
        derived_layer=PipelineLane.WORKING_MEMORY,
        source_event_derived=True,
    ),
    PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE: OutboxJobDefinition(
        job_type=PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
        derived_layer=PipelineLane.PAGE_MEMORY,
        source_event_derived=True,
    ),
    LONG_TERM_FILTER_CLASSIFY_JOB_TYPE: OutboxJobDefinition(
        job_type=LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
        derived_layer=PipelineLane.MEMORY_ITEMS,
        source_event_derived=True,
    ),
    PUSH_CANDIDATE_TRIGGER_JOB_TYPE: OutboxJobDefinition(
        job_type=PUSH_CANDIDATE_TRIGGER_JOB_TYPE,
        derived_layer=None,
        source_event_derived=True,
    ),
    PUSH_CANDIDATE_SEND_JOB_TYPE: OutboxJobDefinition(
        job_type=PUSH_CANDIDATE_SEND_JOB_TYPE,
        derived_layer=None,
        source_event_derived=False,
    ),
}


def source_event_job_types(*, auto_push_enabled: bool = False) -> tuple[str, ...]:
    if auto_push_enabled:
        return (*DEFAULT_SOURCE_EVENT_JOB_TYPES, PUSH_CANDIDATE_TRIGGER_JOB_TYPE)
    return DEFAULT_SOURCE_EVENT_JOB_TYPES


def outbox_job_definition(job_type: str) -> OutboxJobDefinition:
    try:
        return _JOB_DEFINITIONS[job_type]
    except KeyError as exc:
        raise ValueError(f"unsupported outbox job type: {job_type}") from exc


def outbox_job_plan_for_source_event(
    source_event: SourceEvent,
    *,
    job_types: tuple[str, ...] = DEFAULT_SOURCE_EVENT_JOB_TYPES,
) -> OutboxJobCreationPlan:
    return OutboxJobCreationPlan(
        jobs=tuple(
            OutboxJobCreation(
                job_type=job_type,
                aggregate_key=aggregate_key_for_source_event_job(
                    source_event=source_event,
                    job_type=job_type,
                ),
            )
            for job_type in job_types
        )
    )


def aggregate_key_for_source_event_job(
    *,
    source_event: SourceEvent,
    job_type: str,
) -> str:
    if job_type == LONG_TERM_FILTER_CLASSIFY_JOB_TYPE:
        return long_term_filter_aggregate_key(
            project_memory_space_id=source_event.project_memory_space_id,
            group_id=source_event.group_id,
            thread_id=source_event.thread_id,
            shared_group_id=source_event.shared_group_id,
        )
    if job_type == PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE:
        return page_memory_target_from_source_event(source_event).aggregate_key
    return source_event.id


def aggregate_key_for_scope_job(
    *,
    scope: EffectiveScope,
    job_type: str,
) -> str:
    if job_type == LONG_TERM_FILTER_CLASSIFY_JOB_TYPE:
        group_id = scope.group_ids[0] if scope.group_ids and len(scope.group_ids) == 1 else None
        return long_term_filter_aggregate_key(
            project_memory_space_id=scope.project_memory_space_id,
            group_id=group_id,
            thread_id=scope.thread_id,
            shared_group_id=scope.shared_group_id,
        )
    if job_type == PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE:
        return page_memory_trigger_key_for_scope(scope)
    raise ValueError(f"outbox job type does not have a scope aggregate key: {job_type}")


def long_term_filter_aggregate_key(
    *,
    project_memory_space_id: str,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
) -> str:
    return ":".join(
        (
            "long_term_filter",
            project_memory_space_id,
            group_id or "",
            thread_id or "",
            shared_group_id or "",
        )
    )


def derived_layer_for_job_type(job_type: str) -> PipelineLane | None:
    return outbox_job_definition(job_type).derived_layer


def job_type_for_derived_layer(layer: PipelineLane) -> str | None:
    for definition in _JOB_DEFINITIONS.values():
        if definition.derived_layer == layer:
            return definition.job_type
    return None


def job_types_for_worker_lane(lane: str) -> tuple[str, ...] | None:
    if lane in {"all", "outbox"}:
        return None
    if lane == "graph":
        return ()
    if lane == "evidence":
        return (EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,)
    if lane == "working-memory":
        return (WORKING_MEMORY_APPEND_JOB_TYPE,)
    if lane == "page-memory":
        return (PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,)
    if lane == "long-term-filter":
        return (LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,)
    if lane == "push":
        return (PUSH_CANDIDATE_TRIGGER_JOB_TYPE, PUSH_CANDIDATE_SEND_JOB_TYPE)
    raise ValueError(f"unsupported pipeline lane: {lane}")
