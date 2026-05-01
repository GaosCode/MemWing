from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from memwing.core.models import (
    MemoryItem,
    PageMemory,
    PageMemorySynthesis,
    PageMemoryTopic,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.structured_output import parse_json_object
from memwing.ports.model_runtime import LLMModelClient, LLMModelRequest
from memwing.ports.page_memory_synthesis import (
    PageMemorySynthesisPort,
    PageMemorySynthesisRequest,
)


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
    def __init__(self, client: LLMModelClient) -> None:
        self._client = client

    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        response = await self._client.complete(
            LLMModelRequest(
                system_prompt=_PAGE_MEMORY_SYSTEM_PROMPT,
                user_prompt=_page_memory_user_prompt(request),
                trace_id=None,
            )
        )
        parsed = parse_json_object(response.text, source="Page Memory synthesis LLM")
        try:
            output = _PageMemorySynthesisOutput.model_validate(parsed)
        except ValidationError as exc:
            raise LLMOutputSchemaError("Page Memory synthesis LLM output did not match schema") from exc
        return _to_page_memory_synthesis(output)


_PAGE_MEMORY_SYSTEM_PROMPT = """\
You are MemWing Page Memory synthesis. Return compact JSON only, no markdown.
Use only ids from the input. Every topic must cite source_event_ids.
Required shape: {"title":str,"brief":str,"topics":[{"title":str,"summary":str,"source_event_ids":[str],"linked_memory_item_ids":[str]}],"open_questions":[str],"next_steps":[str],"source_event_ids":[str],"linked_memory_item_ids":[str]}.
"""


def _page_memory_user_prompt(request: PageMemorySynthesisRequest) -> str:
    return "\n\n".join(
        (
            f"Scope:\n{_scope_block(request.scope)}",
            f"Source events:\n{_source_events_block(request.source_events)}",
            f"Existing page memory:\n{_existing_page_block(request.existing_page)}",
            f"Linked memory items:\n{_memory_items_block(request.linked_memory_items)}",
            "Synthesize the current page memory now.",
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
    return "\n".join(_source_event_line(event) for event in source_events)


def _source_event_line(event: SourceEvent) -> str:
    content = event.content.strip() or event.content_preview.strip()
    return (
        f"- id={event.id}; time={event.event_time.isoformat()}; "
        f"author={event.author_name or event.author_id or ''}; content={content}"
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
