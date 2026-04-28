from __future__ import annotations

import re


def session_pattern_matches(pattern: str, session_key: str) -> bool:
    return re.fullmatch(_session_pattern_regex(pattern), session_key) is not None


def _session_pattern_regex(pattern: str) -> str:
    parts: list[str] = []
    for char in pattern:
        if char == "*":
            parts.append(".*")
        else:
            parts.append(re.escape(char))
    return "".join(parts)
