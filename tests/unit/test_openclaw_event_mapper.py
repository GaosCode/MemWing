from datetime import UTC, datetime

import pytest

from memwing.api.validation import SchemaValidationError
from memwing.infrastructure.agents.openclaw_event_mapper import (
    OPENCLAW_HOOK_EVENT_TYPES,
    map_openclaw_after_turn_event,
    map_openclaw_hook_event,
    map_openclaw_ingest_event,
)


EVENT_TIME = datetime(2026, 4, 28, 8, 0, tzinfo=UTC)


def test_ingest_generates_stable_idempotency_key_without_changing_contract() -> None:
    event = map_openclaw_ingest_event(
        {
            "agent_id": "main",
            "session_id": "session_001",
            "run_id": "run_001",
            "message_id": "message_001",
            "sequence": 2,
            "scope": {"project_memory_space_id": "project_001"},
            "content": "Remember this decision.",
            "payload": {"kind": "message"},
            "event_time": EVENT_TIME,
        }
    )

    assert event.event_type == "message_ingested"
    assert event.hook_name == "ingest"
    assert event.idempotency_key == "openclaw:main:session_001:run_001:ingest:message_001"
    assert event.scope.project_memory_space_id == "project_001"


def test_after_turn_maps_to_turn_completed() -> None:
    event = map_openclaw_after_turn_event(
        {
            "agent_id": "main",
            "session_id": "session_001",
            "run_id": "run_001",
            "scope": {"project_memory_space_id": "project_001"},
            "content": "Turn completed.",
            "payload": {"success": True},
            "event_time": EVENT_TIME,
        }
    )

    assert event.event_type == "turn_completed"
    assert event.hook_name == "afterTurn"


def test_required_openclaw_hooks_have_event_type_mappings() -> None:
    expected = {
        "after_tool_call": "tool_call_completed",
        "agent_end": "turn_completed",
        "llm_input": "llm_input_observed",
        "llm_output": "llm_output_observed",
        "session_start": "session_started",
        "session_end": "session_ended",
        "before_compaction": "compaction_started",
        "after_compaction": "compaction_completed",
    }

    assert OPENCLAW_HOOK_EVENT_TYPES == expected

    for hook_name, event_type in expected.items():
        event = map_openclaw_hook_event(
            {
                "agent_id": "main",
                "session_id": "session_001",
                "run_id": "run_001",
                "hook_name": hook_name,
                "sequence": 1,
                "scope": {"project_memory_space_id": "project_001"},
                "event_time": "2026-04-28T08:00:00Z",
            }
        )

        assert event.event_type == event_type
        assert event.idempotency_key.endswith(f"{hook_name}:sequence:1")


def test_unsupported_hook_is_rejected() -> None:
    with pytest.raises(SchemaValidationError, match="unsupported OpenClaw hook"):
        map_openclaw_hook_event(
            {
                "agent_id": "main",
                "session_id": "session_001",
                "hook_name": "unknown_hook",
                "scope": {"project_memory_space_id": "project_001"},
                "event_time": EVENT_TIME,
            }
        )
