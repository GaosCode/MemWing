from __future__ import annotations

from dataclasses import dataclass

from memwing.api.control_schema_support import (
    _object_item,
    _optional_text,
    _require_exact_fields,
    _required_bool,
    _required_int,
    _required_text,
    _required_text_tuple,
)
from memwing.api.types import JsonObject
from memwing.api.validation import SchemaValidationError


@dataclass(frozen=True, slots=True)
class ControlPageTopicResponse:
    title: str
    summary: str
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlPageTopicResponse:
        _require_exact_fields(
            payload,
            {"title", "summary", "source_event_ids", "linked_memory_item_ids"},
        )
        return cls(
            title=_required_text(payload, "title"),
            summary=_required_text(payload, "summary"),
            source_event_ids=_required_text_tuple(payload, "source_event_ids"),
            linked_memory_item_ids=_required_text_tuple(payload, "linked_memory_item_ids"),
        )


@dataclass(frozen=True, slots=True)
class ControlPageResponse:
    id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None
    scope_type: str
    scope_id: str
    title: str
    brief: str
    topics: tuple[ControlPageTopicResponse, ...]
    open_questions: tuple[str, ...]
    next_steps: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]
    version: int
    needs_rebuild: bool
    graph_backend_raw_retained: bool
    warning_count: int
    updated_at: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlPageResponse:
        _require_exact_fields(payload, _CONTROL_PAGE_FIELDS)
        topics = payload.get("topics")
        if not isinstance(topics, list | tuple):
            raise SchemaValidationError("topics must be a list")
        return cls(
            id=_required_text(payload, "id"),
            project_memory_space_id=_required_text(payload, "project_memory_space_id"),
            group_id=_optional_text(payload, "group_id"),
            thread_id=_optional_text(payload, "thread_id"),
            shared_group_id=_optional_text(payload, "shared_group_id"),
            scope_type=_required_text(payload, "scope_type"),
            scope_id=_required_text(payload, "scope_id"),
            title=_required_text(payload, "title"),
            brief=_required_text(payload, "brief"),
            topics=tuple(ControlPageTopicResponse.from_json(_object_item(topic, "topics")) for topic in topics),
            open_questions=_required_text_tuple(payload, "open_questions"),
            next_steps=_required_text_tuple(payload, "next_steps"),
            source_event_ids=_required_text_tuple(payload, "source_event_ids"),
            linked_memory_item_ids=_required_text_tuple(payload, "linked_memory_item_ids"),
            version=_required_int(payload, "version"),
            needs_rebuild=_required_bool(payload, "needs_rebuild"),
            graph_backend_raw_retained=_required_bool(payload, "graph_backend_raw_retained"),
            warning_count=_required_int(payload, "warning_count"),
            updated_at=_required_text(payload, "updated_at"),
        )


@dataclass(frozen=True, slots=True)
class ControlPageListResponse:
    items: tuple[ControlPageResponse, ...]
    next_cursor: str | None
    trace_id: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlPageListResponse:
        _require_exact_fields(payload, {"items", "next_cursor", "trace_id"})
        items = payload.get("items")
        if not isinstance(items, list | tuple):
            raise SchemaValidationError("items must be a list")
        return cls(
            items=tuple(ControlPageResponse.from_json(_object_item(item, "items")) for item in items),
            next_cursor=_optional_text(payload, "next_cursor"),
            trace_id=_required_text(payload, "trace_id"),
        )


_CONTROL_PAGE_FIELDS = {
    "id",
    "project_memory_space_id",
    "group_id",
    "thread_id",
    "shared_group_id",
    "scope_type",
    "scope_id",
    "title",
    "brief",
    "topics",
    "open_questions",
    "next_steps",
    "source_event_ids",
    "linked_memory_item_ids",
    "version",
    "needs_rebuild",
    "graph_backend_raw_retained",
    "warning_count",
    "updated_at",
}
