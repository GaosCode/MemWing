from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.page_memory_synthesis import MemWingPageMemorySynthesisAdapter
from memwing.ports.model_runtime import LLMModelRequest, LLMModelResponse
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest


class FakeLLMClient:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.requests: list[LLMModelRequest] = []

    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        self.requests.append(request)
        text = self.texts[min(len(self.requests) - 1, len(self.texts) - 1)]
        return LLMModelResponse(text=text, provider="fake", model="fake")


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


def test_page_memory_synthesis_adapter_caches_validated_json_by_source_lineage() -> None:
    store = InMemoryDataStore()
    llm = FakeLLMClient(
        """
        {
          "title": "Skyline project",
          "brief": "Skyline is the current project codename.",
          "topics": [
            {
              "title": "Project codename",
              "summary": "The durable codename is Skyline.",
              "source_event_ids": ["event_001"]
            }
          ]
        }
        """
    )
    adapter = MemWingPageMemorySynthesisAdapter(
        llm,
        cache_unit_of_work=store,
        cache_runtime="openclaw",
        cache_model="page-model",
        cache_transport="local",
        now=lambda: datetime(2026, 5, 5, tzinfo=UTC),
    )

    first = asyncio.run(adapter.synthesize(_request()))
    second = asyncio.run(adapter.synthesize(_request()))

    assert first == second
    assert len(llm.requests) == 1
    assert adapter.cache_metrics.hits == 1
    assert adapter.cache_metrics.misses == 1
    entries = tuple(store._state.model_result_cache.values())
    assert len(entries) == 1
    assert entries[0].key.prompt_hash == "page_memory_prompt:v2"


def test_page_memory_synthesis_prompt_requires_chinese_for_chinese_inputs() -> None:
    llm = FakeLLMClient(
        """
        {
          "title": "项目代号",
          "brief": "当前项目代号是天际线。",
          "topics": [
            {
              "title": "项目代号",
              "summary": "团队需要在后续状态更新中使用天际线作为项目代号。",
              "source_event_ids": ["event_001"]
            }
          ]
        }
        """
    )
    adapter = MemWingPageMemorySynthesisAdapter(llm)

    asyncio.run(adapter.synthesize(_request()))

    request = llm.requests[0]
    assert "Do not translate Chinese source facts into English" in request.system_prompt
    assert "输出 JSON 中的 title/brief/topics/open_questions/next_steps 必须全部使用中文" in request.user_prompt


def test_page_memory_synthesis_adapter_repairs_schema_once() -> None:
    adapter = MemWingPageMemorySynthesisAdapter(
        FakeLLMClient(
            '{"title":"missing fields"}',
            """
            {
              "title": "Skyline project",
              "brief": "Skyline is the current project codename.",
              "topics": [
                {
                  "title": "Project codename",
                  "summary": "The durable codename is Skyline.",
                  "source_event_ids": ["event_001"]
                }
              ]
            }
            """,
        )
    )

    result = asyncio.run(adapter.synthesize(_request()))

    assert result.title == "Skyline project"
    assert result.source_event_ids == ("event_001",)
    assert result.linked_memory_item_ids == ()
    assert result.topics[0].linked_memory_item_ids == ()
    assert len(adapter._client.requests) == 2
    assert "Previous output failed validation" in adapter._client.requests[1].user_prompt


def test_page_memory_synthesis_adapter_extracts_embedded_json() -> None:
    adapter = MemWingPageMemorySynthesisAdapter(
        FakeLLMClient(
            """
            Here is the JSON:
            {
              "page_memory": {
                "title": "Skyline project",
                "brief": "Skyline remains the durable codename.",
                "topics": [
                  {
                    "title": "Project codename",
                    "summary": "Skyline remains the durable codename.",
                    "source_event_ids": ["event_001"],
                    "linked_memory_item_ids": []
                  }
                ],
                "open_questions": [],
                "next_steps": [],
                "source_event_ids": ["event_001"],
                "linked_memory_item_ids": []
              }
            }
            """
        )
    )

    result = asyncio.run(adapter.synthesize(_request()))

    assert result.title == "Skyline project"
    assert result.source_event_ids == ("event_001",)


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
