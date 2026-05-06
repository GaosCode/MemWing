from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from memwing.core.models import (
    MemoryItem,
    PageMemory,
    PageMemorySynthesis,
    PageMemoryTopic,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.llm.caching_llm import ValidatedLLMJsonCache, ValidatedLLMJsonCacheMetrics
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.structured_output import parse_json_object
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.model_runtime import (
    LLMModelClient,
    LLMModelRequest,
    MemWingModelRuntime,
    MemWingModelTransport,
)
from memwing.ports.page_memory_synthesis import (
    PageMemorySynthesisPort,
    PageMemorySynthesisRequest,
)


_MAX_TOPIC_COUNT = 3
_MAX_SOURCE_IDS_PER_TOPIC = 2


class _PageMemoryTopicOutput(BaseModel):
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    linked_memory_item_ids: tuple[str, ...] = ()


class _PageMemorySynthesisOutput(BaseModel):
    title: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    topics: tuple[_PageMemoryTopicOutput, ...] = Field(min_length=1)
    open_questions: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    linked_memory_item_ids: tuple[str, ...] = ()


class MemWingPageMemorySynthesisAdapter(PageMemorySynthesisPort):
    _MAX_ATTEMPTS = 2

    def __init__(
        self,
        client: LLMModelClient,
        *,
        cache_unit_of_work: EventStoreUnitOfWorkPort | None = None,
        cache_runtime: MemWingModelRuntime | None = None,
        cache_model: str | None = None,
        cache_transport: MemWingModelTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._cache = (
            ValidatedLLMJsonCache(
                cache_unit_of_work,
                role="page_memory",
                runtime=cache_runtime,
                model=cache_model,
                transport=cache_transport,
                prompt_hash="page_memory_prompt:v2",
                schema_hash="page_memory_schema:v1",
                now=now or (lambda: datetime.now(UTC)),
            )
            if cache_unit_of_work is not None
            and cache_runtime is not None
            and cache_model is not None
            and cache_transport is not None
            else None
        )
        self.cache_metrics = (
            self._cache.metrics if self._cache is not None else ValidatedLLMJsonCacheMetrics()
        )

    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        last_error: LLMOutputSchemaError | None = None
        last_text: str | None = None
        user_prompt = _page_memory_user_prompt(request)
        source_event_ids = tuple(event.id for event in request.source_events)
        if self._cache is not None:
            cached = await self._cache.get(
                project_memory_space_id=request.scope.project_memory_space_id,
                source_event_ids=source_event_ids,
                input_text=user_prompt,
            )
            if cached is not None:
                return _to_page_memory_synthesis(_validate_parsed_output(cached))

        for attempt in range(self._MAX_ATTEMPTS):
            response = await self._client.complete(
                LLMModelRequest(
                    system_prompt=_PAGE_MEMORY_SYSTEM_PROMPT,
                    user_prompt=(
                        user_prompt
                        if attempt == 0
                        else _page_memory_repair_prompt(
                            request=request,
                            previous_text=last_text or "",
                            error_message=str(last_error) if last_error is not None else "invalid schema",
                        )
                    ),
                    trace_id=None,
                    cache_context=(
                        self._cache.context(
                            project_memory_space_id=request.scope.project_memory_space_id,
                            source_event_ids=source_event_ids,
                        )
                        if self._cache is not None and attempt == 0
                        else None
                    ),
                )
            )
            if self._cache is not None:
                self._cache.metrics.provider_calls += 1
            last_text = response.text
            try:
                validated = _validate_output(response.text)
                if self._cache is not None and attempt == 0:
                    await self._cache.put(
                        project_memory_space_id=request.scope.project_memory_space_id,
                        source_event_ids=source_event_ids,
                        input_text=user_prompt,
                        value_json=validated.model_dump(mode="json"),
                    )
                return _to_page_memory_synthesis(validated)
            except LLMOutputSchemaError as exc:
                last_error = exc

        raise last_error or LLMOutputSchemaError("Page Memory synthesis LLM output did not match schema")


def _validate_output(text: str) -> _PageMemorySynthesisOutput:
    parsed = _parse_json_object(text, source="Page Memory synthesis LLM")
    return _validate_parsed_output(parsed)


def _validate_parsed_output(parsed: dict[str, Any]) -> _PageMemorySynthesisOutput:
    if isinstance(parsed.get("page_memory"), dict):
        parsed = parsed["page_memory"]
    _fill_optional_arrays(parsed)
    for topic in parsed.get("topics", ()):
        if isinstance(topic, dict):
            _fill_optional_arrays(topic)
    _fill_derived_source_event_ids(parsed)
    try:
        return _PageMemorySynthesisOutput.model_validate(parsed)
    except ValidationError as exc:
        raise LLMOutputSchemaError("Page Memory synthesis LLM output did not match schema") from exc


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _parse_json_object(text: str, *, source: str) -> dict[str, Any]:
    try:
        return parse_json_object(text, source=source)
    except LLMOutputSchemaError as direct_error:
        stripped = text.strip()
        fence = _JSON_FENCE_RE.search(stripped)
        if fence is not None:
            stripped = fence.group(1).strip()
        else:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start >= 0 and end > start:
                stripped = stripped[start : end + 1]
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise direct_error from exc
        if not isinstance(parsed, dict):
            raise LLMOutputSchemaError(f"{source} must be a JSON object")
        return parsed


def _fill_optional_arrays(value: dict[str, Any]) -> None:
    for field_name in ("open_questions", "next_steps", "linked_memory_item_ids"):
        if field_name not in value or value[field_name] is None:
            value[field_name] = []


def _fill_derived_source_event_ids(value: dict[str, Any]) -> None:
    if value.get("source_event_ids"):
        return
    topic_source_ids: list[str] = []
    topics = value.get("topics")
    if not isinstance(topics, list):
        return
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        source_event_ids = topic.get("source_event_ids")
        if isinstance(source_event_ids, list):
            topic_source_ids.extend(item for item in source_event_ids if isinstance(item, str) and item)
    value["source_event_ids"] = tuple(dict.fromkeys(topic_source_ids))


def _page_memory_repair_prompt(
    *,
    request: PageMemorySynthesisRequest,
    previous_text: str,
    error_message: str,
) -> str:
    return "\n\n".join(
        (
            _page_memory_user_prompt(request),
            f"Previous output failed validation: {error_message}",
            f"Previous output:\n{previous_text[:4000]}",
            (
                "Return corrected JSON only. Do not add prose or markdown. "
                "Keep the JSON under 900 characters."
            ),
        )
    )


_PAGE_MEMORY_SYSTEM_PROMPT = """\
You are MemWing Page Memory synthesis. Return one compact JSON object only, no markdown and no prose.
Language policy: when the source events and linked memory items are mainly Chinese, every generated title, brief, topic title, topic summary, open question, and next step must be Chinese. Do not translate Chinese source facts into English. Preserve original Chinese names, terms, dates, thresholds, metrics, and quoted wording.
Use only ids from the input. Every topic must cite non-empty source_event_ids.
Do not cover every source event separately. Merge duplicate or similar events.
Return at most 3 topics. Each topic must cite at most 2 source_event_ids.
Keep title, brief, and summaries short. Keep the whole JSON under 900 characters.
Required minimal shape: {"title":str,"brief":str,"topics":[{"title":str,"summary":str,"source_event_ids":[str]}]}.
Omit linked_memory_item_ids, open_questions, next_steps, and top-level source_event_ids when empty or redundant.
"""


def _page_memory_user_prompt(request: PageMemorySynthesisRequest) -> str:
    return "\n\n".join(
        (
            f"Scope:\n{_scope_block(request.scope)}",
            f"Source events:\n{_source_events_block(request.source_events)}",
            f"Existing page memory:\n{_existing_page_block(request.existing_page)}",
            f"Linked memory items:\n{_memory_items_block(request.linked_memory_items)}",
            f"Allowed linked_memory_item_ids: {', '.join(item.id for item in request.linked_memory_items) or 'none'}",
            "Language requirement:\n"
            "- 如果 Source events 或 Linked memory items 主要是中文，输出 JSON 中的 title/brief/topics/open_questions/next_steps 必须全部使用中文。\n"
            "- 不要把中文事实翻译成英文；保留原文中的项目名、人名、指标、阈值、时间和引用短语。\n"
            "- 如果需要概括，只能用中文概括，不能生成英文泛摘要。",
            (
                "Synthesize the current page memory now. Return JSON only. "
                f"Use no more than {_MAX_TOPIC_COUNT} topics and no more than "
                f"{_MAX_SOURCE_IDS_PER_TOPIC} source_event_ids per topic."
            ),
        )
    )


def _scope_block(scope: EffectiveScope) -> str:
    group_ids = ",".join(scope.group_ids or ())
    return (
        f"project_memory_space_id={scope.project_memory_space_id}\n"
        f"group_ids={group_ids}\n"
        f"thread_id={scope.thread_id or ''}\n"
        f"shared_group_id={scope.shared_group_id or ''}\n"
        f"safe_mode_enabled={scope.safe_mode_enabled}\n"
        f"cross_group_allowed={scope.cross_group_allowed}"
    )


def _source_events_block(source_events: tuple[SourceEvent, ...]) -> str:
    groups: dict[tuple[str, str], list[SourceEvent]] = {}
    for event in source_events:
        content = event.content.strip() or event.content_preview.strip()
        author = event.author_name or event.author_id or ""
        groups.setdefault((content, author), []).append(event)
    return "\n".join(_source_event_group_line(events) for events in groups.values())


def _source_event_group_line(events: list[SourceEvent]) -> str:
    first = events[0]
    content = first.content.strip() or first.content_preview.strip()
    ids = ",".join(event.id for event in events)
    return (
        f"- ids={ids}; first_time={first.event_time.isoformat()}; "
        f"author={first.author_name or first.author_id or ''}; content={content}"
    )


def _existing_page_block(page: PageMemory | None) -> str:
    if page is None:
        return "none"
    topics = "; ".join(f"{topic.title}: {topic.summary}" for topic in page.topics)
    return f"title={page.title}\nbrief={page.brief}\ntopics={topics}"


def _memory_items_block(items: tuple[MemoryItem, ...]) -> str:
    if not items:
        return "none"
    return "\n".join(_memory_item_line(item) for item in items)


def _memory_item_line(item: MemoryItem) -> str:
    return f"- id={item.id}; title={item.title}; content={item.content}"


def _to_page_memory_synthesis(output: _PageMemorySynthesisOutput) -> PageMemorySynthesis:
    return PageMemorySynthesis(
        title=output.title.strip(),
        brief=output.brief.strip(),
        topics=tuple(
            PageMemoryTopic(
                title=topic.title.strip(),
                summary=topic.summary.strip(),
                source_event_ids=topic.source_event_ids,
                linked_memory_item_ids=topic.linked_memory_item_ids,
            )
            for topic in output.topics
        ),
        open_questions=tuple(question.strip() for question in output.open_questions if question.strip()),
        next_steps=tuple(step.strip() for step in output.next_steps if step.strip()),
        source_event_ids=output.source_event_ids,
        linked_memory_item_ids=output.linked_memory_item_ids,
    )
