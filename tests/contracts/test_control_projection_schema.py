from __future__ import annotations

import pytest

from memwing.api.control import (
    ControlIntegrationsResponse,
    ControlForgettingReviewItemResponse,
    ControlMaintenanceResponse,
    ControlPageListResponse,
    ControlSettingsResponse,
    ControlSummaryResponse,
    ControlScopeDirectoryResponse,
    ControlScopeResolveResponse,
    MemoryDetailResponse,
    MemoryListItemResponse,
    MemoryListResponse,
)
from memwing.api.validation import SchemaValidationError


def test_control_memory_list_contract_exposes_backend_derived_fields() -> None:
    response = MemoryListResponse.from_json(
        {
            "items": [
                {
                    "id": "memory_001",
                    "title": "Demo scope",
                    "summary": "Demo scope remains Feishu plus OpenClaw.",
                    "display_type": "decision",
                    "route": "graph",
                    "status": "active",
                    "group_id": "group_001",
                    "thread_id": "thread_001",
                    "source_event_ids": ["source_001"],
                    "decay_score": 0.82,
                    "original_score": 0.91,
                    "half_life_days": 30,
                    "recall_threshold": 0.5,
                    "curve_state": "retained",
                    "last_reinforced_at": "2026-04-28T00:00:00+00:00",
                    "next_review_at": "2026-05-23T12:00:00+00:00",
                    "retention_reason": "score_above_recall_threshold",
                    "flags": ["active", "graph_linked"],
                    "source_state": "available",
                    "graph_backend_raw_retained": False,
                    "available_actions": ["confirm", "archive", "hide"],
                    "warning_count": 0,
                    "updated_at": "2026-04-30T00:00:00+00:00",
                }
            ],
            "next_cursor": None,
            "trace_id": "trace_control_list",
        }
    )

    item = response.items[0]
    assert item.decay_score == 0.82
    assert item.original_score == 0.91
    assert item.half_life_days == 30
    assert item.recall_threshold == 0.5
    assert item.curve_state == "retained"
    assert item.next_review_at == "2026-05-23T12:00:00+00:00"
    assert item.retention_reason == "score_above_recall_threshold"
    assert item.available_actions == ("confirm", "archive", "hide")


def test_control_memory_detail_contract_contains_lineage_and_audit_refs() -> None:
    detail = MemoryDetailResponse.from_json(
        {
            "item": _memory_item_payload(),
            "content": "Demo scope remains Feishu plus OpenClaw.",
            "source_event_ids": ["source_001"],
            "memory_item_ids": ["memory_001"],
            "graph_links": [
                {
                    "id": "graph_link_001",
                    "backend": "graphiti",
                    "backend_object_type": "entity_edge",
                    "backend_object_id": "edge_001",
                    "link_type": "fact",
                }
            ],
            "audit_refs": ["audit_001"],
            "trace_id": "trace_control_detail",
        }
    )

    assert detail.item.id == "memory_001"
    assert detail.graph_links[0].backend == "graphiti"
    assert detail.audit_refs == ("audit_001",)


def test_control_projection_rejects_frontend_only_fields() -> None:
    payload = _memory_item_payload() | {"frontend_badge": "computed in ui"}

    with pytest.raises(SchemaValidationError, match="unsupported field"):
        MemoryListItemResponse.from_json(payload)


def test_forgetting_review_and_maintenance_contracts_are_backend_derived() -> None:
    review = ControlForgettingReviewItemResponse.from_json(
        {
            "id": "forgetting_review_001",
            "memory": _memory_item_payload(decay_score=0.42, curve_state="below_threshold"),
            "threshold": 0.5,
            "reason": "score_below_threshold",
            "created_at": "2026-04-30T00:00:00+00:00",
            "updated_at": "2026-04-30T00:00:00+00:00",
        }
    )
    maintenance = ControlMaintenanceResponse.from_json(
        {
            "forgetting_review_count": 1,
            "pending_push_count": 1,
            "job_count": 2,
            "warning_count": 1,
            "jobs": [
                {
                    "id": "graph_job_001",
                    "kind": "graph_write",
                    "status": "dead_letter",
                    "attempts": 1,
                    "max_attempts": 3,
                    "next_run_at": "2026-04-30T00:00:00+00:00",
                    "last_error": "ProviderPermanentFailure",
                    "dead_letter_reason": "ProviderPermanentFailure",
                    "retryable": False,
                }
            ],
            "push_candidates": [
                {
                    "id": "push_001",
                    "type": "forgetting_review",
                    "title": "Review Demo scope",
                    "status": "pending",
                    "priority": 100,
                    "memory_item_ids": ["memory_001"],
                    "source_event_ids": ["source_001"],
                    "trigger_reason": "score_below_threshold",
                    "created_at": "2026-04-30T00:00:00+00:00",
                }
            ],
            "jobs_next_cursor": None,
            "push_candidates_next_cursor": "offset:2",
            "next_cursor": "offset:2",
            "trace_id": "trace_maintenance",
        }
    )

    assert review.memory.decay_score == 0.42
    assert maintenance.jobs[0].retryable is False
    assert maintenance.push_candidates[0].type == "forgetting_review"
    assert maintenance.jobs_next_cursor is None
    assert maintenance.push_candidates_next_cursor == "offset:2"
    assert maintenance.next_cursor == "offset:2"


def test_control_page_summary_settings_and_integrations_contracts_are_backend_owned() -> None:
    pages = ControlPageListResponse.from_json(
        {
            "items": [
                {
                    "id": "page_001",
                    "project_memory_space_id": "project_001",
                    "group_id": "group_001",
                    "thread_id": "thread_001",
                    "shared_group_id": None,
                    "scope_type": "thread",
                    "scope_id": "thread_001",
                    "title": "Demo page",
                    "brief": "Demo page brief.",
                    "topics": [
                        {
                            "title": "Demo",
                            "summary": "Demo summary",
                            "source_event_ids": ["source_001"],
                            "linked_memory_item_ids": ["memory_001"],
                        }
                    ],
                    "open_questions": ["What ships next?"],
                    "next_steps": ["Review scope"],
                    "source_event_ids": ["source_001"],
                    "linked_memory_item_ids": ["memory_001"],
                    "version": 2,
                    "needs_rebuild": False,
                    "graph_backend_raw_retained": True,
                    "warning_count": 1,
                    "updated_at": "2026-04-30T00:00:00+00:00",
                }
            ],
            "next_cursor": None,
            "trace_id": "trace_pages",
        }
    )
    summary = ControlSummaryResponse.from_json(
        {
            "pending_memory_count": 1,
            "forgetting_review_count": 1,
            "pending_push_count": 1,
            "dead_letter_job_count": 0,
            "warning_count": 1,
            "trace_id": "trace_summary",
        }
    )
    settings = ControlSettingsResponse.from_json(
        {
            "project_memory_space_id": "project_001",
            "safe_mode_enabled": True,
            "shared_group_id": "shared_001",
            "settings_mutation_supported": False,
            "trace_id": "trace_settings",
        }
    )
    integrations = ControlIntegrationsResponse.from_json(
        {
            "items": [{"name": "feishu", "configured": True, "writable": False}],
            "trace_id": "trace_integrations",
        }
    )

    assert pages.items[0].topics[0].source_event_ids == ("source_001",)
    assert summary.dead_letter_job_count == 0
    assert settings.settings_mutation_supported is False
    assert integrations.items[0].writable is False


def test_control_scope_directory_and_resolve_contracts_are_backend_owned() -> None:
    directory = ControlScopeDirectoryResponse.from_json(
        {
            "items": [
                {
                    "project_memory_space_id": "benchmark:20260505-115148:bs001",
                    "name": "Benchmark bs001",
                    "kind": "benchmark",
                    "default_safe_mode_enabled": False,
                    "memory_count": 6,
                    "source_event_count": 13,
                    "page_count": 1,
                    "updated_at": "2026-05-05T11:51:48+00:00",
                    "groups": [
                        {
                            "group_id": "benchmark:bs001",
                            "safe_mode_enabled": True,
                            "shared_group_id": None,
                            "memory_count": 6,
                            "source_event_count": 13,
                            "threads": [
                                {
                                    "thread_id": "benchmark:bs001",
                                    "memory_count": 6,
                                    "source_event_count": 13,
                                    "updated_at": "2026-05-05T11:51:48+00:00",
                                }
                            ],
                        }
                    ],
                }
            ],
            "next_cursor": None,
            "trace_id": "trace_scopes",
        }
    )
    resolved = ControlScopeResolveResponse.from_json(
        {
            "requested_scope": {
                "project_memory_space_id": "benchmark:20260505-115148:bs001",
                "group_id": "benchmark:bs001",
                "thread_id": "benchmark:bs001",
                "shared_group_id": None,
            },
            "effective_scope": {
                "project_memory_space_id": "benchmark:20260505-115148:bs001",
                "group_ids": ["benchmark:bs001"],
                "thread_id": "benchmark:bs001",
                "shared_group_id": None,
                "safe_mode_enabled": True,
                "cross_group_allowed": False,
            },
            "project": {
                "project_memory_space_id": "benchmark:20260505-115148:bs001",
                "name": "Benchmark bs001",
                "kind": "benchmark",
            },
            "trace_id": "trace_scope_resolve",
        }
    )

    assert directory.items[0].kind == "benchmark"
    assert directory.items[0].groups[0].threads[0].thread_id == "benchmark:bs001"
    assert resolved.effective_scope.group_ids == ("benchmark:bs001",)


def _memory_item_payload(
    *,
    decay_score: float = 0.82,
    curve_state: str = "retained",
) -> dict[str, object]:
    return {
        "id": "memory_001",
        "title": "Demo scope",
        "summary": "Demo scope remains Feishu plus OpenClaw.",
        "display_type": "decision",
        "route": "graph",
        "status": "active",
        "group_id": "group_001",
        "thread_id": "thread_001",
        "source_event_ids": ["source_001"],
        "decay_score": decay_score,
        "original_score": 0.91,
        "half_life_days": 30,
        "recall_threshold": 0.5,
        "curve_state": curve_state,
        "last_reinforced_at": "2026-04-28T00:00:00+00:00",
        "next_review_at": "2026-05-23T12:00:00+00:00",
        "retention_reason": "score_above_recall_threshold",
        "flags": ["active", "graph_linked"],
        "source_state": "available",
        "graph_backend_raw_retained": False,
        "available_actions": ["confirm", "archive", "hide"],
        "warning_count": 0,
        "updated_at": "2026-04-30T00:00:00+00:00",
    }
