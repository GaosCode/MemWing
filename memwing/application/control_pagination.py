from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from memwing.core.errors import ValidationFailure


MAX_CONTROL_LIST_LIMIT = 100
CONTROL_FETCH_LIMIT = 500
_CURSOR_PREFIX = "offset:"
_ALLOWED_SORTS = frozenset({"updated_at", "created_at", "event_time", "next_run_at", "priority"})

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ControlListPage(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None
    limit: int
    fetch_limit: int


def control_fetch_limit(*, limit: int, cursor: str | None) -> int:
    normalized_limit = normalize_control_limit(limit)
    return min(_cursor_offset(cursor) + normalized_limit + 1, CONTROL_FETCH_LIMIT)


def paginate_control_items(
    items: Sequence[T],
    *,
    limit: int,
    cursor: str | None,
    sort: str,
    key: Callable[[T], object],
) -> ControlListPage[T]:
    normalized_limit = normalize_control_limit(limit)
    validate_control_sort(sort)
    offset = _cursor_offset(cursor)
    sorted_items = tuple(sorted(items, key=key, reverse=True))
    page = sorted_items[offset : offset + normalized_limit]
    next_offset = offset + normalized_limit
    next_cursor = _encode_cursor(next_offset) if len(sorted_items) > next_offset else None
    return ControlListPage(
        items=page,
        next_cursor=next_cursor,
        limit=normalized_limit,
        fetch_limit=min(next_offset + 1, CONTROL_FETCH_LIMIT),
    )


def normalize_control_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValidationFailure("control_limit_invalid", "Control Plane limit must be an integer.")
    if limit <= 0:
        raise ValidationFailure("control_limit_invalid", "Control Plane limit must be positive.")
    return min(limit, MAX_CONTROL_LIST_LIMIT)


def validate_control_sort(sort: str) -> None:
    if sort not in _ALLOWED_SORTS:
        raise ValidationFailure(
            "control_sort_invalid",
            "Control Plane sort must be updated_at, created_at, event_time, next_run_at, or priority.",
        )


def _cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.startswith(_CURSOR_PREFIX):
        raise ValidationFailure("control_cursor_invalid", "Control Plane cursor is invalid.")
    raw_offset = cursor.removeprefix(_CURSOR_PREFIX)
    if not raw_offset.isdecimal():
        raise ValidationFailure("control_cursor_invalid", "Control Plane cursor is invalid.")
    return int(raw_offset)


def _encode_cursor(offset: int) -> str:
    return f"{_CURSOR_PREFIX}{offset}"
