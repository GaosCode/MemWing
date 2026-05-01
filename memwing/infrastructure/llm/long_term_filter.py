from __future__ import annotations

from datetime import datetime

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
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.structured_output import parse_json_object
from memwing.ports.llm_filter import LongTermFilterPort, LongTermFilterRequest
from memwing.ports.model_runtime import LLMModelClient, LLMModelRequest


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
    def __init__(self, client: LLMModelClient) -> None:
        self._client = client

    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        response = await self._client.complete(
            LLMModelRequest(
                system_prompt=_LONG_TERM_FILTER_SYSTEM_PROMPT,
                user_prompt=_long_term_filter_user_prompt(request),
                trace_id=request.trace_id,
            )
        )
        parsed = parse_json_object(response.text, source="LongTermFilter LLM")
        try:
            output = _LongTermFilterOutput.model_validate(parsed)
        except ValidationError as exc:
            raise LLMOutputSchemaError("LongTermFilter LLM output did not match schema") from exc
        return tuple(_to_filter_item(item) for item in output.items)


_LONG_TERM_FILTER_SYSTEM_PROMPT = """\
You are MemWing LongTermFilter. Return compact JSON only, no markdown.
Promote only durable facts, decisions, preferences, rules, tasks, or evidence. Use only source_event_ids from input.
If nothing is durable, return {"items":[]}.
Required shape: {"items":[{"title":str,"content":str,"route":"graph|vector_only|raw_only|manual","display_type":"decision|task|preference|rule|note|evidence","original_score":float,"half_life_days":int,"source_event_ids":[str],"primary_source_event_id":str|null,"reason":str,"confidence":float,"event_time":str|null,"valid_from":str|null,"valid_to":str|null}]}.
"""


def _long_term_filter_user_prompt(request: LongTermFilterRequest) -> str:
    return "\n\n".join(
        (
            f"Scope:\n{_scope_block(request.scope)}",
            f"Recent page memory:\n{_recent_page_memory_block(request.recent_page_memory)}",
            f"History items:\n{_history_items_block(request.history_items)}",
            f"Evidence snippets:\n{_evidence_snippets_block(request.evidence_snippets)}",
            f"Source events:\n{_source_events_block(request.source_events)}",
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
    topics = "; ".join(f"{topic.title}: {topic.summary}" for topic in page.topics)
    return f"title={page.title}\nbrief={page.brief}\ntopics={topics}"


def _history_items_block(items: tuple[MemoryItem, ...]) -> str:
    if not items:
        return "none"
    return "\n".join(f"- id={item.id}; title={item.title}; content={item.content}" for item in items)


def _evidence_snippets_block(snippets: tuple[EvidenceChunk, ...]) -> str:
    if not snippets:
        return "none"
    return "\n".join(
        f"- id={snippet.id}; source_event_id={snippet.source_event_id}; text={snippet.chunk_text}"
        for snippet in snippets
    )


def _source_events_block(source_events: tuple[SourceEvent, ...]) -> str:
    return "\n".join(_source_event_line(event) for event in source_events)


def _source_event_line(event: SourceEvent) -> str:
    content = event.content.strip() or event.content_preview.strip()
    return (
        f"- id={event.id}; time={event.event_time.isoformat()}; "
        f"author={event.author_name or event.author_id or ''}; content={content}"
    )


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
