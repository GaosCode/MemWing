from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memwing_benchmark.json_utils import loads_json


MEMWING_FULL_DERIVED_READINESS_PROFILE = "full-derived"


def _run_mode_name(*, mode: str, phase: str, batch: bool) -> str:
    suffix = "-batch" if batch else ""
    if mode == "write" and phase != "full":
        return f"write-{phase}{suffix}"
    return f"{mode}{suffix}"

def _empty_raw_records() -> dict[str, Any]:
    return {
        "feishu": [],
        "feishu_commands": [],
        "memwing": [],
        "memwing_http_health": [],
        "memwing_http_search": [],
        "openclaw_plugin_tool_evidence": [],
        "pg_preseed": [],
        "memwing_preseed_expected": [],
        "memwing_ingest": [],
        "memwing_pipeline_drains": [],
        "memwing_readiness": [],
        "memwing_polls": [],
        "openclaw": [],
        "memory_polls": [],
        "memory_searches": [],
        "side_effects": [],
        "debug": [],
    }

def _memwing_pipeline_run_config(
    *,
    pg_preseed_per_case: bool,
    preseed_expected: bool,
) -> dict[str, str]:
    if preseed_expected:
        return {
            "memory_pipeline": "expected_preseed_per_case",
            "readiness_profile": "sync_preseed_expected",
            "graph_backend": "graphiti",
            "page_memory": "preseed_expected",
        }
    if not pg_preseed_per_case:
        return {}
    return {
        "memory_pipeline": "real_ingest_per_case",
        "readiness_profile": MEMWING_FULL_DERIVED_READINESS_PROFILE,
        "graph_backend": "graphiti",
        "evidence_backend": "qdrant",
    }

def _record_memwing_http_records(
    raw_records: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    openclaw_plugin: bool = False,
) -> None:
    raw_records["memwing"] = list(records)
    raw_records["memwing_http_health"] = [
        record for record in records if record.get("kind") == "health"
    ]
    raw_records["memwing_http_search"] = [
        record for record in records if record.get("kind") == "search"
    ]
    if openclaw_plugin:
        existing_evidence = raw_records.get("openclaw_plugin_tool_evidence", [])
        raw_records["openclaw_plugin_tool_evidence"] = existing_evidence or [
            record for record in records if record.get("kind") == "search"
        ]

def _read_json_object(path: Path) -> dict[str, Any]:
    parsed = loads_json(path.read_bytes())
    return parsed if isinstance(parsed, dict) else {}

def _current_truth_branch_timings(raw_diagnostics: object) -> list[dict[str, Any]]:
    if not isinstance(raw_diagnostics, dict):
        return []
    current_truth = raw_diagnostics.get("current_truth")
    if not isinstance(current_truth, dict):
        return []
    branch_timings = current_truth.get("branch_timings")
    if not isinstance(branch_timings, list):
        return []
    return [item for item in branch_timings if isinstance(item, dict)]

def _int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, int)
    }

def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]

def _latency_ms(start_iso: str, end_iso: str) -> int | None:
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return int((end - start).total_seconds() * 1000)
    except Exception:
        return None

def _nested_str(data: dict[str, Any], outer: str, inner: str) -> str | None:
    value = data.get(outer)
    if isinstance(value, dict) and value.get(inner) is not None:
        return str(value[inner])
    return None

def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None

def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None

def _text_list_from_mapping(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
