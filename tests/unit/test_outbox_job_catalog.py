from datetime import UTC, datetime

import pytest

from memwing.application.outbox_job_catalog import (
    EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,
    LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
    PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
    PUSH_CANDIDATE_SEND_JOB_TYPE,
    PUSH_CANDIDATE_TRIGGER_JOB_TYPE,
    WORKING_MEMORY_APPEND_JOB_TYPE,
    aggregate_key_for_scope_job,
    aggregate_key_for_source_event_job,
    derived_layer_for_job_type,
    job_types_for_worker_lane,
    outbox_job_plan_for_source_event,
    source_event_job_types,
)
from memwing.core.models import SourceEvent
from memwing.core.pipeline_readiness import PipelineLane
from memwing.core.scope import EffectiveScope


NOW = datetime(2026, 5, 6, tzinfo=UTC)


def test_source_event_job_plan_preserves_default_job_order_and_aggregate_keys() -> None:
    source = _source_event()

    plan = outbox_job_plan_for_source_event(source)

    assert plan.job_types == (
        EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,
        WORKING_MEMORY_APPEND_JOB_TYPE,
        PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
        LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
    )
    assert {job.job_type: job.aggregate_key for job in plan.jobs} == {
        EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE: "source_001",
        WORKING_MEMORY_APPEND_JOB_TYPE: "source_001",
        PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE: "page_memory:project_001:thread:thread_001",
        LONG_TERM_FILTER_CLASSIFY_JOB_TYPE: "long_term_filter:project_001:group_001:thread_001:shared_001",
    }


def test_auto_push_source_event_job_type_is_catalogued_without_changing_defaults() -> None:
    assert source_event_job_types() == (
        EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,
        WORKING_MEMORY_APPEND_JOB_TYPE,
        PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
        LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
    )
    assert source_event_job_types(auto_push_enabled=True) == (
        EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,
        WORKING_MEMORY_APPEND_JOB_TYPE,
        PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
        LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
        PUSH_CANDIDATE_TRIGGER_JOB_TYPE,
    )
    assert (
        aggregate_key_for_source_event_job(
            source_event=_source_event(),
            job_type=PUSH_CANDIDATE_TRIGGER_JOB_TYPE,
        )
        == "source_001"
    )


def test_scope_aggregate_keys_match_existing_scope_level_workers() -> None:
    scope = EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )

    assert (
        aggregate_key_for_scope_job(scope=scope, job_type=PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE)
        == "page_memory:project_001:thread:thread_001"
    )
    assert (
        aggregate_key_for_scope_job(scope=scope, job_type=LONG_TERM_FILTER_CLASSIFY_JOB_TYPE)
        == "long_term_filter:project_001:group_001:thread_001:"
    )
    with pytest.raises(ValueError, match="does not have a scope aggregate key"):
        aggregate_key_for_scope_job(scope=scope, job_type=WORKING_MEMORY_APPEND_JOB_TYPE)


def test_catalog_maps_worker_lanes_and_readiness_layers() -> None:
    assert job_types_for_worker_lane("evidence") == (EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE,)
    assert job_types_for_worker_lane("working-memory") == (WORKING_MEMORY_APPEND_JOB_TYPE,)
    assert job_types_for_worker_lane("page-memory") == (PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,)
    assert job_types_for_worker_lane("long-term-filter") == (LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,)
    assert job_types_for_worker_lane("push") == (
        PUSH_CANDIDATE_TRIGGER_JOB_TYPE,
        PUSH_CANDIDATE_SEND_JOB_TYPE,
    )
    assert job_types_for_worker_lane("graph") == ()
    assert job_types_for_worker_lane("outbox") is None

    assert derived_layer_for_job_type(EVIDENCE_INDEX_SOURCE_EVENT_JOB_TYPE) == PipelineLane.EVIDENCE
    assert derived_layer_for_job_type(WORKING_MEMORY_APPEND_JOB_TYPE) == PipelineLane.WORKING_MEMORY
    assert derived_layer_for_job_type(PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE) == PipelineLane.PAGE_MEMORY
    assert derived_layer_for_job_type(LONG_TERM_FILTER_CLASSIFY_JOB_TYPE) == PipelineLane.MEMORY_ITEMS
    assert derived_layer_for_job_type(PUSH_CANDIDATE_TRIGGER_JOB_TYPE) is None


def _source_event() -> SourceEvent:
    return SourceEvent(
        id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id="shared_001",
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content="Launch decision",
        content_preview="Launch decision",
        source_url=None,
        event_time=NOW,
        raw_payload_hash="hash",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
    )
