from __future__ import annotations

from typing import TypeAlias


JsonValue: TypeAlias = (
    None | bool | int | float | str | tuple["JsonValue", ...] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]
