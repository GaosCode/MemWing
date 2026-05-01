from __future__ import annotations

from typing import cast

from memwing.api.types import JsonObject
from memwing.api.validation import SchemaValidationError, require_text


def _require_exact_fields(payload: JsonObject, allowed: set[str]) -> None:
    missing = allowed - payload.keys()
    if missing:
        raise SchemaValidationError(f"{sorted(missing)[0]} is required")
    extra = payload.keys() - allowed
    if extra:
        raise SchemaValidationError(f"unsupported field: {sorted(extra)[0]}")


def _object_field(payload: JsonObject, field_name: str) -> JsonObject:
    return _object_item(payload.get(field_name), field_name)


def _object_item(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{field_name} must contain objects")
    return cast(JsonObject, value)


def _required_text(payload: JsonObject, field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} is required")
    return require_text(value, field_name)


def _optional_text(payload: JsonObject, field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be text")
    return require_text(value, field_name)


def _required_text_tuple(payload: JsonObject, field_name: str) -> tuple[str, ...]:
    value = payload.get(field_name)
    if not isinstance(value, list | tuple):
        raise SchemaValidationError(f"{field_name} must be a list")
    return _text_tuple(value, field_name)


def _text_tuple(value: tuple[str, ...] | list[object] | tuple[object, ...], field_name: str) -> tuple[str, ...]:
    return tuple(require_text(item, field_name) for item in value)


def _required_number(payload: JsonObject, field_name: str) -> float:
    value = payload.get(field_name)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a number")
    return float(value)


def _required_int(payload: JsonObject, field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be an integer")
    return value


def _required_bool(payload: JsonObject, field_name: str) -> bool:
    value = payload.get(field_name)
    if not isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be boolean")
    return value


def _bounded_score(value: float, field_name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a number")
    if value < 0 or value > 1:
        raise SchemaValidationError(f"{field_name} must be between 0 and 1")
    return float(value)


def _positive_int(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value <= 0:
        raise SchemaValidationError(f"{field_name} must be positive")
    return value


def _non_negative_int(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value < 0:
        raise SchemaValidationError(f"{field_name} must be non-negative")
    return value
