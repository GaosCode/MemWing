from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from memwing.core.models import (
    EvidenceChunk,
    LongTermFilterItem,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    PageMemory,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.llm.caching_llm import ValidatedLLMJsonCache, ValidatedLLMJsonCacheMetrics
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.structured_output import parse_json_object
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.llm_filter import LongTermFilterPort, LongTermFilterRequest
from memwing.ports.model_runtime import (
    LLMModelClient,
    LLMModelRequest,
    MemWingModelRuntime,
    MemWingModelTransport,
)


class _LongTermFilterItemOutput(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    route: MemoryRoute
    display_type: MemoryDisplayType
    original_score: float = Field(ge=0.0, le=1.0)
    half_life_days: int = Field(ge=1)
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    primary_source_event_id: str | None = None
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    event_time: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class _LongTermFilterOutput(BaseModel):
    items: tuple[_LongTermFilterItemOutput, ...] = ()


class MemWingLongTermFilterAdapter(LongTermFilterPort):
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
                role="long_term_filter",
                runtime=cache_runtime,
                model=cache_model,
                transport=cache_transport,
                prompt_hash="long_term_filter_prompt:v3",
                schema_hash="long_term_filter_schema:v1",
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

    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        _debug_ltf(
            f"filter_events: {len(request.source_events)} source_events, "
            f"{len(request.history_items)} history_items, "
            f"page_memory={'present' if request.recent_page_memory else 'none'}"
        )
        last_error: LLMOutputSchemaError | None = None
        last_text: str | None = None
        user_prompt = _long_term_filter_user_prompt(request)
        source_event_ids = tuple(event.id for event in request.source_events)
        if self._cache is not None:
            cached = await self._cache.get(
                project_memory_space_id=request.scope.project_memory_space_id,
                source_event_ids=source_event_ids,
                input_text=user_prompt,
            )
            if cached is not None:
                return tuple(_to_filter_item(item) for item in _validate_parsed_output(cached).items)

        for attempt in range(self._MAX_ATTEMPTS):
            response = await self._client.complete(
                LLMModelRequest(
                    system_prompt=_LONG_TERM_FILTER_SYSTEM_PROMPT,
                    user_prompt=(
                        user_prompt
                        if attempt == 0
                        else _long_term_filter_repair_prompt(
                            request=request,
                            previous_text=last_text or "",
                            error_message=str(last_error) if last_error is not None else "invalid schema",
                        )
                    ),
                    trace_id=request.trace_id,
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
                return tuple(_to_filter_item(item) for item in validated.items)
            except LLMOutputSchemaError as exc:
                last_error = exc

        raise last_error or LLMOutputSchemaError("LongTermFilter LLM output did not match schema")


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _validate_output(text: str) -> _LongTermFilterOutput:
    parsed = _parse_json_object(text, source="LongTermFilter LLM")
    return _validate_parsed_output(parsed)


def _validate_parsed_output(parsed: dict[str, Any]) -> _LongTermFilterOutput:
    _fill_item_defaults(parsed)
    try:
        return _LongTermFilterOutput.model_validate(parsed)
    except ValidationError as exc:
        raise LLMOutputSchemaError("LongTermFilter LLM output did not match schema") from exc


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


def _fill_item_defaults(parsed: dict[str, Any]) -> None:
    items = parsed.get("items")
    if items is None:
        parsed["items"] = []
        return
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        source_event_ids = item.get("source_event_ids")
        if isinstance(source_event_ids, list) and source_event_ids:
            item.setdefault("primary_source_event_id", source_event_ids[0])
        item.setdefault("original_score", item.get("confidence", 0.75))
        item.setdefault("half_life_days", 180)
        item.setdefault("event_time", None)
        item.setdefault("valid_from", None)
        item.setdefault("valid_to", None)


_DEBUG_LTF = os.environ.get("MEMWING_DEBUG_OPENCLAW") == "1"


def _debug_ltf(msg: str) -> None:
    if not _DEBUG_LTF:
        return
    print(f"[ltf] {msg}", file=sys.stderr, flush=True)


_LONG_TERM_FILTER_SYSTEM_PROMPT = """\
You are MemWing LongTermFilter. Return compact JSON only, no markdown.
Language policy: when the source events are mainly Chinese, every generated title, content, reason, note, and summary-like field must be Chinese. Do not translate Chinese source facts into English. Preserve original Chinese names, terms, dates, thresholds, metrics, and quoted wording.
Source events and evidence indexes already retain raw messages; do not promote items just to preserve text.
Promote only durable, reusable, scope-relevant current facts, decisions, preferences, rules, owners, deadlines, constraints, or project-critical tasks.
Reject noise: one-off logistics, meeting links or reschedules, shared-doc notices, password resets, routine reminders, procurement/admin chores, transient test alerts, training/material updates, marketing assets, and broad summaries unless they define a lasting project rule, owner, deadline, constraint, or decision.
Reject stale intermediate states when a later source supersedes them; promote the latest current truth and cite the superseding source.
Do not bundle unrelated messages into a generic summary. Prefer no item when durability or project relevance is uncertain.
If nothing is durable, return {"items":[]}.
Return at most 4 items. Each item must cite 1-2 source_event_ids.
Required minimal shape: {"items":[{"title":str,"content":str,"route":"graph|vector_only|raw_only|manual","display_type":"decision|task|preference|rule|note|evidence","source_event_ids":[str],"reason":str,"confidence":float}]}.
Omit nullable fields and scoring defaults when redundant.
"""


def _long_term_filter_repair_prompt(
    *,
    request: LongTermFilterRequest,
    previous_text: str,
    error_message: str,
) -> str:
    return "\n\n".join(
        (
            _long_term_filter_user_prompt(request),
            f"Previous output failed validation: {error_message}",
            f"Previous output:\n{previous_text[:4000]}",
            "Return corrected compact JSON only. Do not add prose or markdown.",
        )
    )


def _long_term_filter_user_prompt(request: LongTermFilterRequest) -> str:
    return "\n\n".join(
        (
            f"Scope:\n{_scope_block(request.scope)}",
            f"Recent page memory:\n{_recent_page_memory_block(request.recent_page_memory)}",
            f"History items:\n{_history_items_block(request.history_items)}",
            f"Evidence snippets:\n{_evidence_snippets_block(request.evidence_snippets)}",
            f"Source events:\n{_source_events_block(request.source_events)}",
            "Language requirement:\n"
            "- 如果 Source events 主要是中文，输出 JSON 中的 title/content/reason 必须全部使用中文。\n"
            "- 不要把中文事实翻译成英文；保留原文中的项目名、人名、指标、阈值、时间和引用短语。\n"
            "- 如果需要压缩表达，只能用中文改写，不能改变事实粒度。",
            "Layer boundary:\n"
            "- source_events are the authoritative raw record.\n"
            "- evidence snippets are searchable raw evidence, not durable memory candidates by default.\n"
            "- LongTermFilter should output only compact long-term memory_items.",
            "Durability test:\n"
            "- Would this still help answer a future project question or decision after days or weeks?\n"
            "- Is it a current project fact, owner, deadline, scope, rule, constraint, preference, or decision?\n"
            "- Is it stronger than a one-off notification, transient operational detail, or unrelated side topic?",
            "Classify durable long-term memory candidates now.",
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


def _recent_page_memory_block(page: PageMemory | None) -> str:
    if page is None:
        return "none"
    topics = "; ".join(
        f"{_short_text(topic.title, 40)}: {_short_text(topic.summary, 120)}"
        for topic in page.topics
    )
    return f"title={_short_text(page.title, 80)}\nbrief={_short_text(page.brief, 160)}\ntopics={topics}"


def _history_items_block(items: tuple[MemoryItem, ...]) -> str:
    if not items:
        return "none"
    return "\n".join(
        f"- id={item.id}; title={_short_text(item.title, 80)}; content={_short_text(item.content, 180)}"
        for item in items
    )


def _evidence_snippets_block(snippets: tuple[EvidenceChunk, ...]) -> str:
    if not snippets:
        return "none"
    return "\n".join(
        f"- id={snippet.id}; source_event_id={snippet.source_event_id}; text={_short_text(snippet.chunk_text, 180)}"
        for snippet in snippets
    )


def _source_events_block(source_events: tuple[SourceEvent, ...]) -> str:
    return "\n".join(_source_event_line(event) for event in source_events)


def _source_event_line(event: SourceEvent) -> str:
    content = event.content.strip() or event.content_preview.strip()
    return (
        f"- id={event.id}; time={event.event_time.isoformat()}; "
        f"author={event.author_name or event.author_id or ''}; content={_short_text(content, 180)}"
    )


def _short_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def _to_filter_item(output: _LongTermFilterItemOutput) -> LongTermFilterItem:
    return LongTermFilterItem(
        title=output.title.strip(),
        content=output.content.strip(),
        route=output.route,
        display_type=output.display_type,
        original_score=output.original_score,
        half_life_days=output.half_life_days,
        source_event_ids=output.source_event_ids,
        primary_source_event_id=output.primary_source_event_id,
        reason=output.reason.strip(),
        confidence=output.confidence,
        event_time=output.event_time,
        valid_from=output.valid_from,
        valid_to=output.valid_to,
    )
