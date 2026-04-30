from __future__ import annotations

import json
import re
from typing import Any

from memwing.infrastructure.llm.errors import LLMOutputSchemaError


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_json_object(text: str, *, source: str) -> dict[str, Any]:
    stripped = text.strip()
    match = _JSON_FENCE_RE.match(stripped)
    if match is not None:
        stripped = match.group(1).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMOutputSchemaError(f"{source} returned invalid JSON") from exc

    if not isinstance(parsed, dict):
        raise LLMOutputSchemaError(f"{source} must be a JSON object")
    return parsed
