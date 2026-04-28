from __future__ import annotations

import re


SQL_LIKE_ESCAPE = "!"


def session_pattern_matches(pattern: str, session_key: str) -> bool:
    return re.fullmatch(_session_pattern_regex(pattern), session_key) is not None


def session_pattern_to_sql_like(pattern: str) -> str:
    parts: list[str] = []
    for char in pattern:
        if char == "*":
            parts.append("%")
        elif char in (SQL_LIKE_ESCAPE, "%", "_"):
            parts.append(f"{SQL_LIKE_ESCAPE}{char}")
        else:
            parts.append(char)
    return "".join(parts)


def _session_pattern_regex(pattern: str) -> str:
    parts: list[str] = []
    for char in pattern:
        if char == "*":
            parts.append(".*")
        else:
            parts.append(re.escape(char))
    return "".join(parts)
