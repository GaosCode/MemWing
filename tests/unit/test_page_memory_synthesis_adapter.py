from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.page_memory_synthesis import MemWingPageMemorySynthesisAdapter
from memwing.ports.model_runtime import LLMModelRequest, LLMModelResponse
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest


class FakeLLMClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMModelRequest] = []

    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        self.requests.append(request)
        return LLMModelResponse(text=self.text, provider="fake", model="fake")


def test_page_memory_synthesis_adapter_maps_json_to_contract() -> None:
    llm = FakeLLMClient(
        """
        {
          "title": "Skyline project",
          "brief": "The team chose Skyline as the durable project codename.",
          "topics": [
            {
              "title": "Project codename",
              "summary": "Skyline is the durable codename.",
              "source_event_ids": ["event_001"],
              "linked_memory_item_ids": []
            }
          ],
          "open_questions": [],
          "next_steps": ["Use Skyline in future status updates."],
          "source_event_ids": ["event_001"],
          "linked_memory_item_ids": []
        }
        """
    )
    adapter = MemWingPageMemorySynthesisAdapter(llm)

    result = asyncio.run(adapter.synthesize(_request()))

    assert result.title == "Skyline project"
    assert result.source_event_ids == ("event_001",)
    assert result.topics[0].source_event_ids == ("event_001",)
    assert "source_events" not in llm.requests[0].system_prompt
    assert "event_001" in llm.requests[0].user_prompt


def test_page_memory_synthesis_adapter_rejects_malformed_json() -> None:
    adapter = MemWingPageMemorySynthesisAdapter(FakeLLMClient('{"title":"missing fields"}'))

    with pytest.raises(LLMOutputSchemaError, match="did not match schema"):
        asyncio.run(adapter.synthesize(_request()))


def _request() -> PageMemorySynthesisRequest:
    return PageMemorySynthesisRequest(
        scope=EffectiveScope(
            project_memory_space_id="project_001",
            group_ids=("group_001",),
            thread_id="thread_001",
            shared_group_id=None,
            safe_mode_enabled=True,
            cross_group_allowed=False,
        ),
        source_events=(_source_event(),),
        existing_page=None,
        linked_memory_items=(),
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
