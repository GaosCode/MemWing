from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from memwing.api.types import JsonObject
from memwing.api.validation import SchemaValidationError, require_text
from memwing.core.models import MemoryDisplayType, MemoryStatus


@dataclass(frozen=True, slots=True)
class MemoryListItemResponse:
    id: str
    title: str
    display_type: MemoryDisplayType
    source_label: str
    last_seen: str
    status: MemoryStatus
    strength: float
    flags: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_text(self.id, "id"))
        object.__setattr__(self, "title", require_text(self.title, "title"))
        object.__setattr__(self, "source_label", require_text(self.source_label, "source_label"))
        object.__setattr__(self, "last_seen", require_text(self.last_seen, "last_seen"))
        object.__setattr__(self, "reason", require_text(self.reason, "reason"))
        if not isinstance(self.strength, int | float) or isinstance(self.strength, bool):
            raise SchemaValidationError("strength must be a number")
        if self.strength < 0 or self.strength > 1:
            raise SchemaValidationError("strength must be between 0 and 1")
        object.__setattr__(self, "strength", float(self.strength))
        object.__setattr__(self, "flags", tuple(require_text(flag, "flags") for flag in self.flags))

    @classmethod
    def from_json(cls, payload: JsonObject) -> MemoryListItemResponse:
        flags = payload.get("flags")
        if not isinstance(flags, list | tuple):
            raise SchemaValidationError("flags must be a list")
        return cls(
            id=_required_text(payload, "id"),
            title=_required_text(payload, "title"),
            display_type=_memory_display_type(payload),
            source_label=_required_text(payload, "source_label"),
            last_seen=_required_text(payload, "last_seen"),
            status=_memory_status(payload),
            strength=_required_number(payload, "strength"),
            flags=tuple(cast(tuple[str, ...], tuple(flags))),
            reason=_required_text(payload, "reason"),
        )


@dataclass(frozen=True, slots=True)
class MemoryListResponse:
    items: tuple[MemoryListItemResponse, ...]
    next_cursor: str | None
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if self.next_cursor is not None:
            object.__setattr__(
                self,
                "next_cursor",
                require_text(self.next_cursor, "next_cursor"),
            )
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))

    @classmethod
    def from_json(cls, payload: JsonObject) -> MemoryListResponse:
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


def _object_item(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{field_name} must contain objects")
    return cast(JsonObject, value)


def _required_text(payload: JsonObject, field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} is required")
    return require_text(value, field_name)


def _required_number(payload: JsonObject, field_name: str) -> float:
    value = payload.get(field_name)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a number")
    return float(value)


def _memory_display_type(payload: JsonObject) -> MemoryDisplayType:
    value = _required_text(payload, "display_type")
    try:
        return MemoryDisplayType(value)
    except ValueError as exc:
        raise SchemaValidationError("display_type is not supported") from exc


def _memory_status(payload: JsonObject) -> MemoryStatus:
    value = _required_text(payload, "status")
    try:
        return MemoryStatus(value)
    except ValueError as exc:
        raise SchemaValidationError("status is not supported") from exc
