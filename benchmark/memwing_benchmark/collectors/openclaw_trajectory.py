from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memwing_benchmark.json_utils import loads_json, walk_values
from memwing_benchmark.metrics.retrieval import extract_evidence_ids, unique_preserve_order
from memwing_benchmark.schema import TokenUsage


class ParsedTrajectory(BaseModel):
    paths: list[Path] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    memory_recall_latency_ms: int | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    raw_tool_events: list[dict[str, Any]] = Field(default_factory=list)
    missing_reason: str | None = None


def parse_trajectory_dir(path: Path | None) -> ParsedTrajectory:
    if path is None:
        return ParsedTrajectory(missing_reason="OpenClaw trajectory not found")
    path = path.expanduser()
    if not path.exists():
        return ParsedTrajectory(missing_reason="OpenClaw trajectory not found")
    files = [path] if path.is_file() else sorted(path.rglob("*.jsonl"))
    if not files:
        return ParsedTrajectory(missing_reason="OpenClaw trajectory not found")

    evidence: list[str] = []
    raw_tool_events: list[dict[str, Any]] = []
    recall_latency: int | None = None
    tokens = TokenUsage(available=False, missing_reason="provider did not expose usage")

    for file_path in files:
        for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = loads_json(stripped)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            event_text = stripped
            if "memory_search" in event_text or "memory_get" in event_text:
                raw_tool_events.append(event)
                evidence.extend(extract_evidence_ids(event_text))
                latency = _find_first_number(event, {"searchMs", "search_ms", "latency_ms"})
                if latency is not None:
                    recall_latency = int(latency)
            usage = _find_usage(event)
            if usage is not None:
                tokens = usage

    return ParsedTrajectory(
        paths=files,
        evidence_ids=unique_preserve_order(evidence),
        memory_recall_latency_ms=recall_latency,
        tokens=tokens,
        raw_tool_events=raw_tool_events,
        missing_reason=None,
    )


def _find_first_number(value: Any, keys: set[str]) -> int | float | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, int | float):
                return child
            nested = _find_first_number(child, keys)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _find_first_number(child, keys)
            if nested is not None:
                return nested
    return None


def _find_usage(event: dict[str, Any]) -> TokenUsage | None:
    for value in walk_values(event):
        if not isinstance(value, dict):
            continue
        input_tokens = value.get("input_tokens", value.get("input"))
        output_tokens = value.get("output_tokens", value.get("output"))
        total_tokens = value.get("total_tokens", value.get("total"))
        if any(isinstance(v, int) for v in (input_tokens, output_tokens, total_tokens)):
            return TokenUsage(
                input=input_tokens if isinstance(input_tokens, int) else None,
                output=output_tokens if isinstance(output_tokens, int) else None,
                total=total_tokens if isinstance(total_tokens, int) else None,
                source="openclaw_trajectory",
                available=True,
                missing_reason=None,
            )
    return None
