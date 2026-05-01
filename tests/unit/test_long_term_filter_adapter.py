from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.long_term_filter import MemWingLongTermFilterAdapter
from memwing.ports.llm_filter import LongTermFilterRequest
from memwing.ports.model_runtime import LLMModelRequest, LLMModelResponse


class FakeLLMClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMModelRequest] = []

    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        self.requests.append(request)
        return LLMModelResponse(text=self.text, provider="fake", model="fake")


def test_long_term_filter_adapter_maps_json_to_contract() -> None:
    llm = FakeLLMClient(
        """
        {
          "items": [
            {
              "title": "Skyline codename",
              "content": "The project codename is Skyline.",
              "route": "graph",
              "display_type": "note",
              "original_score": 0.92,
              "half_life_days": 180,
              "source_event_ids": ["event_001"],
              "primary_source_event_id": "event_001",
              "reason": "The user explicitly asked this to be remembered.",
              "confidence": 0.98,
              "event_time": "2026-01-01T00:00:00+00:00",
              "valid_from": null,
              "valid_to": null
            }
          ]
        }
        """
    )
    adapter = MemWingLongTermFilterAdapter(llm)

    result = asyncio.run(adapter.filter_events(_request()))

    assert len(result) == 1
    assert result[0].title == "Skyline codename"
    assert result[0].route == "graph"
    assert result[0].display_type == "note"
    assert result[0].source_event_ids == ("event_001",)
    assert result[0].event_time == datetime(2026, 1, 1, tzinfo=UTC)
    assert llm.requests[0].trace_id == "trace_001"
    assert "event_001" in llm.requests[0].user_prompt


def test_long_term_filter_adapter_allows_empty_candidate_list() -> None:
    adapter = MemWingLongTermFilterAdapter(FakeLLMClient('{"items":[]}'))

    assert asyncio.run(adapter.filter_events(_request())) == ()


def test_long_term_filter_adapter_rejects_malformed_json() -> None:
    adapter = MemWingLongTermFilterAdapter(
        FakeLLMClient('{"items":[{"title":"missing fields"}]}')
    )

    with pytest.raises(LLMOutputSchemaError, match="did not match schema"):
        asyncio.run(adapter.filter_events(_request()))


def _request() -> LongTermFilterRequest:
    return LongTermFilterRequest(
        scope=EffectiveScope(
            project_memory_space_id="project_001",
            group_ids=("group_001",),
            thread_id="thread_001",
            shared_group_id=None,
            safe_mode_enabled=True,
            cross_group_allowed=False,
        ),
        source_events=(_source_event(),),
        recent_page_memory=None,
        history_items=(),
        evidence_snippets=(),
        trace_id="trace_001",
    )


def _source_event() -> SourceEvent:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SourceEvent(
        id="event_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Alice",
        source_type="message",
        content="Remember that the project codename is Skyline.",
        content_preview="Remember that the project codename is Skyline.",
        source_url=None,
        event_time=now,
        raw_payload_hash="hash_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=True,
        created_at=now,
    )
