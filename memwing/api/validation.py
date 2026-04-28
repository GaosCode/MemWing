from __future__ import annotations


class SchemaValidationError(ValueError):
    """Raised when a boundary schema receives semantically invalid input."""


def require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} is required")
    return value


def require_positive_int(value: int, field_name: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return value


def require_non_negative_float(value: float, field_name: str) -> float:
    if not isinstance(value, int | float) or value < 0:
        raise SchemaValidationError(f"{field_name} must be a non-negative number")
    return float(value)
