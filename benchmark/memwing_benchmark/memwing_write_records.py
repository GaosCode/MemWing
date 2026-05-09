from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memwing_benchmark.adapters.memwing import MemWingAdapter, MemWingCaseScope
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.metrics.retrieval import unique_preserve_order
from memwing_benchmark.run_records import (
    MEMWING_FULL_DERIVED_READINESS_PROFILE,
    _read_json_object,
)
from memwing_benchmark.run_support import debug as _debug
from memwing_benchmark.schema import BenchmarkCase


@dataclass(frozen=True)
class MemWingWriteIngestRecord:
    case_id: str
    run_id: str
    run_dir: Path
    scope: MemWingCaseScope
    source_event_ids: list[str]
    selection: str

def _await_memwing_write_evaluate_readiness(
    *,
    adapter: MemWingAdapter,
    case: BenchmarkCase,
    ingest_record: MemWingWriteIngestRecord | None,
    raw_records: dict[str, Any],
    runs_root: Path,
    requested_ingest_run_id: str | None,
) -> dict[str, Any]:
    if ingest_record is None or not ingest_record.source_event_ids:
        raw_records.setdefault("memwing_pipeline_awaits", []).append(
            {
                "case_id": case.case_id,
                "profile": "write-evaluate",
                "available": False,
                "reason": "source_event_ids_required",
                "runs_root": str(runs_root),
                "requested_ingest_run_id": requested_ingest_run_id,
            }
        )
        raise BenchmarkError(
            "MemWing write evaluate requires source_event_ids from a prior write-ingest run: "
            f"case_id={case.case_id} runs_root={runs_root} ingest_run_id={requested_ingest_run_id or 'latest'}"
        )

    _debug(
        raw_records,
        "MemWing write evaluate pipeline await 开始",
        case_id=case.case_id,
        source_event_count=len(ingest_record.source_event_ids),
        ingest_run_id=ingest_record.run_id,
        ingest_selection=ingest_record.selection,
    )
    drain = adapter.drain_benchmark_pipeline(
        ingest_record.scope,
        max_rounds=50,
        batch_size=max(10, len(ingest_record.source_event_ids)),
    )
    raw_records.setdefault("memwing_pipeline_drains", []).append(
        {
            "case_id": case.case_id,
            "scope": ingest_record.scope.payload(),
            "ingest_run_id": ingest_record.run_id,
            "response": drain,
        }
    )
    if drain.get("drained") is not True:
        raise BenchmarkError(
            f"MemWing write-evaluate pipeline drain did not finish: case_id={case.case_id}"
        )
    readiness = adapter.pipeline_await(
        scope=ingest_record.scope,
        source_event_ids=ingest_record.source_event_ids,
        profile=MEMWING_FULL_DERIVED_READINESS_PROFILE,
    )
    raw_records.setdefault("memwing_pipeline_awaits", []).append(
        {
            "case_id": case.case_id,
            "scope": ingest_record.scope.payload(),
            "source_event_ids": ingest_record.source_event_ids,
            "profile": MEMWING_FULL_DERIVED_READINESS_PROFILE,
            "ingest_run_id": ingest_record.run_id,
            "ingest_run_dir": str(ingest_record.run_dir),
            "ingest_selection": ingest_record.selection,
            "response": readiness,
        }
    )
    if readiness.get("ready") is not True:
        raise BenchmarkError(f"MemWing write-evaluate pipeline await did not become ready: case_id={case.case_id}")
    _debug(raw_records, "MemWing write evaluate pipeline await 完成", case_id=case.case_id)
    return readiness

def _load_memwing_write_ingest_records(
    *,
    runs_root: Path,
    backend: str,
    adapter: MemWingAdapter,
    case_ids: list[str],
    ingest_run_id: str | None,
) -> dict[str, MemWingWriteIngestRecord]:
    missing = set(case_ids)
    records: dict[str, MemWingWriteIngestRecord] = {}
    ingest_root = runs_root / "write-ingest"
    if not ingest_root.exists():
        return records

    raw_paths = sorted(
        ingest_root.glob("*/*/raw/records.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for raw_path in raw_paths:
        if not missing:
            break
        run_dir = raw_path.parent.parent
        config_path = run_dir / "config.json"
        if not config_path.exists():
            continue
        run_config = _read_json_object(config_path)
        if (
            run_config.get("backend") != backend
            or run_config.get("mode") != "write"
            or run_config.get("phase") != "ingest"
        ):
            continue
        run_id = run_config.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            continue
        if ingest_run_id is not None and run_id != ingest_run_id:
            continue
        raw_records = _read_json_object(raw_path)
        for write_record in raw_records.get("memory_writes", ()):
            if not isinstance(write_record, dict) or write_record.get("phase") != "ingest":
                continue
            case_id = write_record.get("case_id")
            if not isinstance(case_id, str) or case_id not in missing:
                continue
            source_event_ids = [
                source_event_id
                for source_event_id in write_record.get("source_event_ids", ())
                if isinstance(source_event_id, str) and source_event_id
            ]
            if not source_event_ids:
                continue
            scope = _memwing_scope_from_raw(
                write_record.get("scope"),
                default_scope=_memwing_default_scope(adapter),
            )
            if not _is_benchmark_scope(scope):
                if ingest_run_id is not None:
                    raise BenchmarkError(
                        "MemWing write evaluate requires a benchmark-scoped ingest run: "
                        f"case_id={case_id} ingest_run_id={run_id} "
                        f"project_memory_space_id={scope.project_memory_space_id}. "
                        "Rerun write ingest so the scope is benchmark:{run_id}:{case_id}."
                    )
                continue
            records[case_id] = MemWingWriteIngestRecord(
                case_id=case_id,
                run_id=run_id,
                run_dir=run_dir,
                scope=scope,
                source_event_ids=unique_preserve_order(source_event_ids),
                selection="explicit" if ingest_run_id is not None else "latest-compatible",
            )
            missing.remove(case_id)
    return records

def _memwing_default_scope(adapter: MemWingAdapter) -> MemWingCaseScope:
    return MemWingCaseScope(
        project_memory_space_id=adapter.config.project_memory_space_id,
        group_id=adapter.config.group_id,
        thread_id=adapter.config.thread_id,
        shared_group_id=adapter.config.shared_group_id or None,
    )

def _memwing_scope_from_raw(value: Any, *, default_scope: MemWingCaseScope) -> MemWingCaseScope:
    if not isinstance(value, dict):
        return default_scope
    project_memory_space_id = value.get("project_memory_space_id")
    group_id = value.get("group_id")
    thread_id = value.get("thread_id")
    shared_group_id = value.get("shared_group_id")
    if not isinstance(project_memory_space_id, str) or not project_memory_space_id:
        return default_scope
    if not isinstance(group_id, str) or not group_id:
        return default_scope
    if not isinstance(thread_id, str) or not thread_id:
        return default_scope
    return MemWingCaseScope(
        project_memory_space_id=project_memory_space_id,
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id if isinstance(shared_group_id, str) and shared_group_id else None,
    )

def _is_benchmark_scope(scope: MemWingCaseScope) -> bool:
    return scope.project_memory_space_id.startswith("benchmark:")
