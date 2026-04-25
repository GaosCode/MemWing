from __future__ import annotations

import json
import re
from typing import Any

import orjson


JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def loads_json(data: str | bytes) -> Any:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return orjson.loads(data)


def dumps_json(data: Any) -> str:
    return orjson.dumps(data, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS).decode("utf-8")


def dumps_jsonl_row(data: Any) -> str:
    return orjson.dumps(data).decode("utf-8")


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fence = JSON_FENCE_RE.search(stripped)
    if fence:
        stripped = fence.group(1).strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def walk_values(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)
