from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from memwing.core.models import MemoryDisplayType, MemoryItem, MemoryRoute, MemoryStatus, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.long_term_filter import MemWingLongTermFilterAdapter
from memwing.ports.llm_filter import LongTermFilterRequest
from memwing.ports.model_runtime import LLMModelRequest, LLMModelResponse


class FakeLLMClient:
    def __init__(self, text: str | list[str]) -> None:
        self.texts = [text] if isinstance(text, str) else text
        self.requests: list[LLMModelRequest] = []

    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.texts) - 1)
        return LLMModelResponse(text=self.texts[index], provider="fake", model="fake")


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


def test_long_term_filter_adapter_caches_validated_json_by_source_lineage() -> None:
    llm = FakeLLMClient(
        """
        {
          "items": [
            {
              "title": "Skyline codename",
              "content": "The project codename is Skyline.",
              "route": "graph",
              "display_type": "note",
              "source_event_ids": ["event_001"],
              "reason": "Durable project fact.",
              "confidence": 0.98
            }
          ]
        }
        """
    )
    adapter = MemWingLongTermFilterAdapter(
        llm,
        cache_unit_of_work=InMemoryDataStore(),
        cache_runtime="openclaw",
        cache_model="filter-model",
        cache_transport="local",
        now=lambda: datetime(2026, 5, 5, tzinfo=UTC),
    )

    first = asyncio.run(adapter.filter_events(_request()))
    second = asyncio.run(adapter.filter_events(_request()))

    assert first == second
    assert len(llm.requests) == 1
    assert adapter.cache_metrics.hits == 1
    assert adapter.cache_metrics.misses == 1


def test_long_term_filter_adapter_uses_v3_prompt_hash_for_cache() -> None:
    store = InMemoryDataStore()
    adapter = MemWingLongTermFilterAdapter(
        FakeLLMClient('{"items":[]}'),
        cache_unit_of_work=store,
        cache_runtime="openclaw",
        cache_model="filter-model",
        cache_transport="local",
        now=lambda: datetime(2026, 5, 5, tzinfo=UTC),
    )

    asyncio.run(adapter.filter_events(_request()))

    entries = tuple(store._state.model_result_cache.values())
    assert len(entries) == 1
    assert entries[0].key.prompt_hash == "long_term_filter_prompt:v3"


def test_long_term_filter_prompt_defines_noise_and_layer_boundary() -> None:
    llm = FakeLLMClient('{"items":[]}')
    adapter = MemWingLongTermFilterAdapter(llm)

    asyncio.run(adapter.filter_events(_request()))

    request = llm.requests[0]
    assert "Source events and evidence indexes already retain raw messages" in request.system_prompt
    assert "Do not translate Chinese source facts into English" in request.system_prompt
    assert "Reject noise" in request.system_prompt
    assert "transient test alerts" in request.system_prompt
    assert "Do not bundle unrelated messages into a generic summary" in request.system_prompt
    assert "输出 JSON 中的 title/content/reason 必须全部使用中文" in request.user_prompt
    assert "source_events are the authoritative raw record" in request.user_prompt
    assert "evidence snippets are searchable raw evidence" in request.user_prompt
    assert "one-off notification" in request.user_prompt


def test_long_term_filter_adapter_fills_compact_item_defaults() -> None:
    adapter = MemWingLongTermFilterAdapter(
        FakeLLMClient(
            """
            ```json
            {
              "items": [
                {
                  "title": "Skyline codename",
                  "content": "The project codename is Skyline.",
                  "route": "vector_only",
                  "display_type": "note",
                  "source_event_ids": ["event_001"],
                  "reason": "Durable project fact.",
                  "confidence": 0.88
                }
              ]
            }
            ```
            """
        )
    )

    result = asyncio.run(adapter.filter_events(_request()))

    assert result[0].primary_source_event_id == "event_001"
    assert result[0].original_score == 0.88
    assert result[0].half_life_days == 180


def test_long_term_filter_adapter_repairs_schema_once() -> None:
    adapter = MemWingLongTermFilterAdapter(
        FakeLLMClient(
            [
                '{"items":[{"title":"missing fields"}]}',
                """
                {
                  "items": [
                    {
                      "title": "Skyline codename",
                      "content": "The project codename is Skyline.",
                      "route": "vector_only",
                      "display_type": "note",
                      "source_event_ids": ["event_001"],
                      "reason": "Durable project fact.",
                      "confidence": 0.9
                    }
                  ]
                }
                """,
            ]
        )
    )

    result = asyncio.run(adapter.filter_events(_request()))

    assert len(result) == 1
    assert result[0].source_event_ids == ("event_001",)


def test_long_term_filter_adapter_rejects_malformed_json() -> None:
    adapter = MemWingLongTermFilterAdapter(
        FakeLLMClient('{"items":[{"title":"missing fields"}]}')
    )

    with pytest.raises(LLMOutputSchemaError, match="did not match schema"):
        asyncio.run(adapter.filter_events(_request()))


def test_long_term_filter_eval_catches_omitted_explicit_memory() -> None:
    result = _evaluate_case(
        request=_request(
            source_events=(
                _source_event(
                    source_event_id="event_001",
                    content="Please remember: the durable project codename is Skyline.",
                ),
            )
        ),
        llm_text='{"items":[]}',
        expected_titles=("Skyline codename",),
    )

    assert not result.passed
    assert result.reason == "missing expected candidate: Skyline codename"


def test_long_term_filter_eval_accepts_low_value_noise_as_empty_output() -> None:
    result = _evaluate_case(
        request=_request(
            source_events=(
                _source_event(
                    source_event_id="event_noise",
                    content="Thanks, got it. Nice.",
                ),
            )
        ),
        llm_text='{"items":[]}',
        expected_titles=(),
    )

    assert result.passed


def test_long_term_filter_eval_tracks_conflicting_fact_as_new_candidate() -> None:
    result = _evaluate_case(
        request=_request(
            source_events=(
                _source_event(
                    source_event_id="event_new",
                    content="The project codename changed to Skyline.",
                ),
            ),
            history_items=(
                _memory_item(
                    memory_id="memory_old",
                    title="Apollo codename",
                    content="The project codename is Apollo.",
                    source_event_id="event_old",
                ),
            ),
        ),
        llm_text="""
        {
          "items": [
            {
              "title": "Skyline codename",
              "content": "The project codename changed to Skyline.",
              "route": "graph",
              "display_type": "decision",
              "original_score": 0.9,
              "half_life_days": 180,
              "source_event_ids": ["event_new"],
              "primary_source_event_id": "event_new",
              "reason": "The new source event supersedes the prior codename.",
              "confidence": 0.93,
              "event_time": "2026-01-01T00:00:00+00:00",
              "valid_from": null,
              "valid_to": null
            }
          ]
        }
        """,
        expected_titles=("Skyline codename",),
    )

    assert result.passed


def test_long_term_filter_eval_flags_misextracted_source_lineage() -> None:
    result = _evaluate_case(
        request=_request(
            source_events=(
                _source_event(
                    source_event_id="event_001",
                    content="Please remember: the durable project codename is Skyline.",
                ),
            )
        ),
        llm_text="""
        {
          "items": [
            {
              "title": "Skyline codename",
              "content": "The project codename is Skyline.",
              "route": "graph",
              "display_type": "decision",
              "original_score": 0.9,
              "half_life_days": 180,
              "source_event_ids": ["event_missing"],
              "primary_source_event_id": "event_missing",
              "reason": "The user explicitly asked this to be remembered.",
              "confidence": 0.93,
              "event_time": "2026-01-01T00:00:00+00:00",
              "valid_from": null,
              "valid_to": null
            }
          ]
        }
        """,
        expected_titles=("Skyline codename",),
    )

    assert not result.passed
    assert result.reason == "candidate references unloaded source_event_id: event_missing"


@dataclass(frozen=True, slots=True)
class _EvalResult:
    passed: bool
    reason: str | None = None


def _evaluate_case(
    *,
    request: LongTermFilterRequest,
    llm_text: str,
    expected_titles: tuple[str, ...],
) -> _EvalResult:
    candidates = asyncio.run(MemWingLongTermFilterAdapter(FakeLLMClient(llm_text)).filter_events(request))
    loaded_source_ids = {event.id for event in request.source_events}
    for candidate in candidates:
        for source_event_id in candidate.source_event_ids:
            if source_event_id not in loaded_source_ids:
                return _EvalResult(
                    passed=False,
                    reason=f"candidate references unloaded source_event_id: {source_event_id}",
                )

    candidate_titles = {candidate.title for candidate in candidates}
    for expected_title in expected_titles:
        if expected_title not in candidate_titles:
            return _EvalResult(
                passed=False,
                reason=f"missing expected candidate: {expected_title}",
            )
    if not expected_titles and candidates:
        return _EvalResult(passed=False, reason="unexpected candidates for low-value noise")
    return _EvalResult(passed=True)


def _request(
    *,
    source_events: tuple[SourceEvent, ...] | None = None,
    history_items: tuple[MemoryItem, ...] = (),
) -> LongTermFilterRequest:
    return LongTermFilterRequest(
        scope=EffectiveScope(
            project_memory_space_id="project_001",
            group_ids=("group_001",),
            thread_id="thread_001",
            shared_group_id=None,
            safe_mode_enabled=True,
            cross_group_allowed=False,
        ),
        source_events=source_events or (_source_event(),),
        recent_page_memory=None,
        history_items=history_items,
        evidence_snippets=(),
        trace_id="trace_001",
    )


def _source_event(
    *,
    source_event_id: str = "event_001",
    content: str = "Remember that the project codename is Skyline.",
) -> SourceEvent:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Alice",
        source_type="message",
        content=content,
        content_preview=content,
        source_url=None,
        event_time=now,
        raw_payload_hash=f"hash:{source_event_id}",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=True,
        created_at=now,
    )


def _memory_item(
    *,
    memory_id: str,
    title: str,
    content: str,
    source_event_id: str,
) -> MemoryItem:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title=title,
        content=content,
        summary=None,
        source_event_ids=(source_event_id,),
        primary_source_event_id=source_event_id,
        status=MemoryStatus.ACTIVE,
        event_time=now,
        valid_from=None,
        valid_to=None,
        original_score=0.9,
        half_life_days=180,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=now,
        activated_at=now,
        updated_at=now,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )
