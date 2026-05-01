from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from memwing.api.control_pages import (
    ControlPageListResponse as ControlPageListResponse,
    ControlPageResponse as ControlPageResponse,
    ControlPageTopicResponse as ControlPageTopicResponse,
)
from memwing.api.control_schema_support import (
    _bounded_score,
    _non_negative_int,
    _object_field,
    _object_item,
    _optional_text,
    _positive_int,
    _require_exact_fields,
    _required_bool,
    _required_int,
    _required_number,
    _required_text,
    _required_text_tuple,
    _text_tuple,
)
from memwing.api.types import JsonObject
from memwing.api.validation import SchemaValidationError, require_text
from memwing.core.models import (
    MemoryDisplayType,
    MemoryRoute,
    MemoryStatus,
    PushCandidateType,
)


@dataclass(frozen=True, slots=True)
class MemoryListItemResponse:
    id: str
    title: str
    summary: str | None
    display_type: MemoryDisplayType
    route: MemoryRoute
    status: MemoryStatus
    group_id: str | None
    thread_id: str | None
    source_event_ids: tuple[str, ...]
    decay_score: float
    original_score: float
    half_life_days: int
    recall_threshold: float
    curve_state: str
    last_reinforced_at: str
    next_review_at: str | None
    retention_reason: str
    flags: tuple[str, ...]
    source_state: str
    graph_backend_raw_retained: bool
    available_actions: tuple[str, ...]
    warning_count: int
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_text(self.id, "id"))
        object.__setattr__(self, "title", require_text(self.title, "title"))
        if self.summary is not None:
            object.__setattr__(self, "summary", require_text(self.summary, "summary"))
        object.__setattr__(self, "source_event_ids", _text_tuple(self.source_event_ids, "source_event_ids"))
        object.__setattr__(self, "decay_score", _bounded_score(self.decay_score, "decay_score"))
        object.__setattr__(self, "original_score", _bounded_score(self.original_score, "original_score"))
        object.__setattr__(self, "half_life_days", _positive_int(self.half_life_days, "half_life_days"))
        object.__setattr__(
            self,
            "recall_threshold",
            _bounded_score(self.recall_threshold, "recall_threshold"),
        )
        object.__setattr__(self, "curve_state", require_text(self.curve_state, "curve_state"))
        object.__setattr__(
            self,
            "last_reinforced_at",
            require_text(self.last_reinforced_at, "last_reinforced_at"),
        )
        if self.next_review_at is not None:
            object.__setattr__(
                self,
                "next_review_at",
                require_text(self.next_review_at, "next_review_at"),
            )
        object.__setattr__(
            self,
            "retention_reason",
            require_text(self.retention_reason, "retention_reason"),
        )
        object.__setattr__(self, "flags", _text_tuple(self.flags, "flags"))
        object.__setattr__(self, "source_state", require_text(self.source_state, "source_state"))
        if not isinstance(self.graph_backend_raw_retained, bool):
            raise SchemaValidationError("graph_backend_raw_retained must be boolean")
        object.__setattr__(
            self,
            "available_actions",
            _text_tuple(self.available_actions, "available_actions"),
        )
        object.__setattr__(self, "warning_count", _non_negative_int(self.warning_count, "warning_count"))
        object.__setattr__(self, "updated_at", require_text(self.updated_at, "updated_at"))

    @classmethod
    def from_json(cls, payload: JsonObject) -> MemoryListItemResponse:
        _require_exact_fields(payload, _MEMORY_LIST_ITEM_FIELDS)
        return cls(
            id=_required_text(payload, "id"),
            title=_required_text(payload, "title"),
            summary=_optional_text(payload, "summary"),
            display_type=_memory_display_type(payload),
            route=_memory_route(payload),
            status=_memory_status(payload),
            group_id=_optional_text(payload, "group_id"),
            thread_id=_optional_text(payload, "thread_id"),
            source_event_ids=_required_text_tuple(payload, "source_event_ids"),
            decay_score=_required_number(payload, "decay_score"),
            original_score=_required_number(payload, "original_score"),
            half_life_days=_required_int(payload, "half_life_days"),
            recall_threshold=_required_number(payload, "recall_threshold"),
            curve_state=_required_text(payload, "curve_state"),
            last_reinforced_at=_required_text(payload, "last_reinforced_at"),
            next_review_at=_optional_text(payload, "next_review_at"),
            retention_reason=_required_text(payload, "retention_reason"),
            flags=_required_text_tuple(payload, "flags"),
            source_state=_required_text(payload, "source_state"),
            graph_backend_raw_retained=_required_bool(payload, "graph_backend_raw_retained"),
            available_actions=_required_text_tuple(payload, "available_actions"),
            warning_count=_required_int(payload, "warning_count"),
            updated_at=_required_text(payload, "updated_at"),
        )


@dataclass(frozen=True, slots=True)
class MemoryListResponse:
    items: tuple[MemoryListItemResponse, ...]
    next_cursor: str | None
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if self.next_cursor is not None:
            object.__setattr__(self, "next_cursor", require_text(self.next_cursor, "next_cursor"))
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))

    @classmethod
    def from_json(cls, payload: JsonObject) -> MemoryListResponse:
        _require_exact_fields(payload, {"items", "next_cursor", "trace_id"})
        items = payload.get("items")
        if not isinstance(items, list | tuple):
            raise SchemaValidationError("items must be a list")
        next_cursor = payload.get("next_cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise SchemaValidationError("next_cursor must be text")
        return cls(
            items=tuple(
                MemoryListItemResponse.from_json(_object_item(item, "items")) for item in items
            ),
            next_cursor=next_cursor,
            trace_id=_required_text(payload, "trace_id"),
        )


@dataclass(frozen=True, slots=True)
class ControlGraphLinkResponse:
    id: str
    backend: str
    backend_object_type: str
    backend_object_id: str
    link_type: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlGraphLinkResponse:
        _require_exact_fields(
            payload,
            {"id", "backend", "backend_object_type", "backend_object_id", "link_type"},
        )
        return cls(
            id=_required_text(payload, "id"),
            backend=_required_text(payload, "backend"),
            backend_object_type=_required_text(payload, "backend_object_type"),
            backend_object_id=_required_text(payload, "backend_object_id"),
            link_type=_required_text(payload, "link_type"),
        )


@dataclass(frozen=True, slots=True)
class MemoryDetailResponse:
    item: MemoryListItemResponse
    content: str
    source_event_ids: tuple[str, ...]
    memory_item_ids: tuple[str, ...]
    graph_links: tuple[ControlGraphLinkResponse, ...]
    audit_refs: tuple[str, ...]
    trace_id: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> MemoryDetailResponse:
        _require_exact_fields(
            payload,
            {
                "item",
                "content",
                "source_event_ids",
                "memory_item_ids",
                "graph_links",
                "audit_refs",
                "trace_id",
            },
        )
        graph_links = payload.get("graph_links")
        if not isinstance(graph_links, list | tuple):
            raise SchemaValidationError("graph_links must be a list")
        return cls(
            item=MemoryListItemResponse.from_json(_object_field(payload, "item")),
            content=_required_text(payload, "content"),
            source_event_ids=_required_text_tuple(payload, "source_event_ids"),
            memory_item_ids=_required_text_tuple(payload, "memory_item_ids"),
            graph_links=tuple(
                ControlGraphLinkResponse.from_json(_object_item(link, "graph_links"))
                for link in graph_links
            ),
            audit_refs=_required_text_tuple(payload, "audit_refs"),
            trace_id=_required_text(payload, "trace_id"),
        )


@dataclass(frozen=True, slots=True)
class ControlForgettingReviewItemResponse:
    id: str
    memory: MemoryListItemResponse
    threshold: float
    reason: str
    created_at: str
    updated_at: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlForgettingReviewItemResponse:
        _require_exact_fields(payload, {"id", "memory", "threshold", "reason", "created_at", "updated_at"})
        return cls(
            id=_required_text(payload, "id"),
            memory=MemoryListItemResponse.from_json(_object_field(payload, "memory")),
            threshold=_required_number(payload, "threshold"),
            reason=_required_text(payload, "reason"),
            created_at=_required_text(payload, "created_at"),
            updated_at=_required_text(payload, "updated_at"),
        )


@dataclass(frozen=True, slots=True)
class ControlJobResponse:
    id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    next_run_at: str
    last_error: str | None
    dead_letter_reason: str | None
    retryable: bool

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlJobResponse:
        _require_exact_fields(
            payload,
            {
                "id",
                "kind",
                "status",
                "attempts",
                "max_attempts",
                "next_run_at",
                "last_error",
                "dead_letter_reason",
                "retryable",
            },
        )
        return cls(
            id=_required_text(payload, "id"),
            kind=_required_text(payload, "kind"),
            status=_required_text(payload, "status"),
            attempts=_required_int(payload, "attempts"),
            max_attempts=_required_int(payload, "max_attempts"),
            next_run_at=_required_text(payload, "next_run_at"),
            last_error=_optional_text(payload, "last_error"),
            dead_letter_reason=_optional_text(payload, "dead_letter_reason"),
            retryable=_required_bool(payload, "retryable"),
        )


@dataclass(frozen=True, slots=True)
class ControlPushCandidateResponse:
    id: str
    type: PushCandidateType
    title: str
    status: str
    priority: int
    memory_item_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    trigger_reason: str
    created_at: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlPushCandidateResponse:
        _require_exact_fields(
            payload,
            {
                "id",
                "type",
                "title",
                "status",
                "priority",
                "memory_item_ids",
                "source_event_ids",
                "trigger_reason",
                "created_at",
            },
        )
        return cls(
            id=_required_text(payload, "id"),
            type=cast(PushCandidateType, _required_text(payload, "type")),
            title=_required_text(payload, "title"),
            status=_required_text(payload, "status"),
            priority=_required_int(payload, "priority"),
            memory_item_ids=_required_text_tuple(payload, "memory_item_ids"),
            source_event_ids=_required_text_tuple(payload, "source_event_ids"),
            trigger_reason=_required_text(payload, "trigger_reason"),
            created_at=_required_text(payload, "created_at"),
        )


@dataclass(frozen=True, slots=True)
class ControlMaintenanceResponse:
    forgetting_review_count: int
    pending_push_count: int
    job_count: int
    warning_count: int
    jobs: tuple[ControlJobResponse, ...]
    push_candidates: tuple[ControlPushCandidateResponse, ...]
    next_cursor: str | None
    trace_id: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlMaintenanceResponse:
        _require_exact_fields(
            payload,
            {
                "forgetting_review_count",
                "pending_push_count",
                "job_count",
                "warning_count",
                "jobs",
                "push_candidates",
                "next_cursor",
                "trace_id",
            },
        )
        jobs = payload.get("jobs")
        push_candidates = payload.get("push_candidates")
        if not isinstance(jobs, list | tuple):
            raise SchemaValidationError("jobs must be a list")
        if not isinstance(push_candidates, list | tuple):
            raise SchemaValidationError("push_candidates must be a list")
        return cls(
            forgetting_review_count=_required_int(payload, "forgetting_review_count"),
            pending_push_count=_required_int(payload, "pending_push_count"),
            job_count=_required_int(payload, "job_count"),
            warning_count=_required_int(payload, "warning_count"),
            jobs=tuple(ControlJobResponse.from_json(_object_item(job, "jobs")) for job in jobs),
            push_candidates=tuple(
                ControlPushCandidateResponse.from_json(_object_item(candidate, "push_candidates"))
                for candidate in push_candidates
            ),
            next_cursor=_optional_text(payload, "next_cursor"),
            trace_id=_required_text(payload, "trace_id"),
        )


@dataclass(frozen=True, slots=True)
class ControlSummaryResponse:
    pending_memory_count: int
    forgetting_review_count: int
    pending_push_count: int
    dead_letter_job_count: int
    warning_count: int
    trace_id: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlSummaryResponse:
        _require_exact_fields(
            payload,
            {
                "pending_memory_count",
                "forgetting_review_count",
                "pending_push_count",
                "dead_letter_job_count",
                "warning_count",
                "trace_id",
            },
        )
        return cls(
            pending_memory_count=_required_int(payload, "pending_memory_count"),
            forgetting_review_count=_required_int(payload, "forgetting_review_count"),
            pending_push_count=_required_int(payload, "pending_push_count"),
            dead_letter_job_count=_required_int(payload, "dead_letter_job_count"),
            warning_count=_required_int(payload, "warning_count"),
            trace_id=_required_text(payload, "trace_id"),
        )


@dataclass(frozen=True, slots=True)
class ControlSettingsResponse:
    project_memory_space_id: str
    safe_mode_enabled: bool
    shared_group_id: str | None
    settings_mutation_supported: bool
    trace_id: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlSettingsResponse:
        _require_exact_fields(
            payload,
            {
                "project_memory_space_id",
                "safe_mode_enabled",
                "shared_group_id",
                "settings_mutation_supported",
                "trace_id",
            },
        )
        return cls(
            project_memory_space_id=_required_text(payload, "project_memory_space_id"),
            safe_mode_enabled=_required_bool(payload, "safe_mode_enabled"),
            shared_group_id=_optional_text(payload, "shared_group_id"),
            settings_mutation_supported=_required_bool(payload, "settings_mutation_supported"),
            trace_id=_required_text(payload, "trace_id"),
        )


@dataclass(frozen=True, slots=True)
class ControlIntegrationResponse:
    name: str
    configured: bool
    writable: bool

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlIntegrationResponse:
        _require_exact_fields(payload, {"name", "configured", "writable"})
        return cls(
            name=_required_text(payload, "name"),
            configured=_required_bool(payload, "configured"),
            writable=_required_bool(payload, "writable"),
        )


@dataclass(frozen=True, slots=True)
class ControlIntegrationsResponse:
    items: tuple[ControlIntegrationResponse, ...]
    trace_id: str

    @classmethod
    def from_json(cls, payload: JsonObject) -> ControlIntegrationsResponse:
        _require_exact_fields(payload, {"items", "trace_id"})
        items = payload.get("items")
        if not isinstance(items, list | tuple):
            raise SchemaValidationError("items must be a list")
        return cls(
            items=tuple(ControlIntegrationResponse.from_json(_object_item(item, "items")) for item in items),
            trace_id=_required_text(payload, "trace_id"),
        )


_MEMORY_LIST_ITEM_FIELDS = {
    "id",
    "title",
    "summary",
    "display_type",
    "route",
    "status",
    "group_id",
    "thread_id",
    "source_event_ids",
    "decay_score",
    "original_score",
    "half_life_days",
    "recall_threshold",
    "curve_state",
    "last_reinforced_at",
    "next_review_at",
    "retention_reason",
    "flags",
    "source_state",
    "graph_backend_raw_retained",
    "available_actions",
    "warning_count",
    "updated_at",
}



def _memory_display_type(payload: JsonObject) -> MemoryDisplayType:
    value = _required_text(payload, "display_type")
    try:
        return MemoryDisplayType(value)
    except ValueError as exc:
        raise SchemaValidationError("display_type is not supported") from exc


def _memory_route(payload: JsonObject) -> MemoryRoute:
    value = _required_text(payload, "route")
    try:
        return MemoryRoute(value)
    except ValueError as exc:
        raise SchemaValidationError("route is not supported") from exc


def _memory_status(payload: JsonObject) -> MemoryStatus:
    value = _required_text(payload, "status")
    try:
        return MemoryStatus(value)
    except ValueError as exc:
        raise SchemaValidationError("status is not supported") from exc
