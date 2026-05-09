from __future__ import annotations

from pathlib import Path

from memwing_benchmark.adapters.memwing import MemWingAdapter
from memwing_benchmark.config import apply_overrides, load_config, sanitize_config_for_run, validate_config_for_backend
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluation import _build_judge
from memwing_benchmark.memwing_retrieval import _run_memwing_preseeded_retrieval_batch
from memwing_benchmark.report import write_run_outputs
from memwing_benchmark.run_command_support import MEMWING_HTTP_BACKEND, _preflight_memwing_http
from memwing_benchmark.run_records import _empty_raw_records, _record_memwing_http_records
from memwing_benchmark.schema import load_cases, make_run_id, utc_now_iso

def _run_memwing_preseeded_evaluate_command(
    *,
    config_path: Path,
    cases_path: Path,
    source_run_id: str,
    case_id: str | None,
    batch: bool,
    limit: int,
    runs_dir: Path | None,
    health_check: bool,
) -> Path:
    source_run_id = _optional_cli_text(source_run_id, "--run-id") or source_run_id
    if limit <= 0:
        raise BenchmarkError("--limit must be greater than 0")
    config = apply_overrides(load_config(config_path), runs_dir=runs_dir, chat_id=None, trajectory_dir=None)
    validate_config_for_backend(config, backend=MEMWING_HTTP_BACKEND)
    cases = load_cases(cases_path, case_id=case_id)
    if not batch and len(cases) != 1:
        raise BenchmarkError("non-batch runs require exactly one case; pass --case-id or --batch")
    judge = _build_judge(config)
    if judge is None:
        raise BenchmarkError("evaluate-preseeded requires a configured judge api key")

    eval_run_id = make_run_id()
    run_day = eval_run_id.split("-", 1)[0]
    run_mode = "retrieval-evaluate"
    run_dir = Path(config.paths.runs_dir).expanduser() / run_mode / run_day / eval_run_id
    started_at = utc_now_iso()
    raw_records = _empty_raw_records()
    adapter = MemWingAdapter(config.memwing)
    if health_check:
        _preflight_memwing_http(adapter=adapter, raw_records=raw_records)
    results = _run_memwing_preseeded_retrieval_batch(
        eval_run_id=eval_run_id,
        source_run_id=source_run_id,
        backend=MEMWING_HTTP_BACKEND,
        cases=cases,
        adapter=adapter,
        judge=judge,
        raw_records=raw_records,
        limit=limit,
    )
    _record_memwing_http_records(raw_records, adapter.records)
    finished_at = utc_now_iso()
    write_run_outputs(
        run_dir=run_dir,
        run_config={
            "benchmark_version": "v1",
            "backend": MEMWING_HTTP_BACKEND,
            "mode": "retrieval",
            "phase": "evaluate-preseeded",
            "run_id": eval_run_id,
            "run_mode": run_mode,
            "run_day": run_day,
            "source_run_id": source_run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "case_file": str(cases_path),
            "case_ids": [case.case_id for case in cases],
            "batch": batch,
            "chat_id": None,
            "seed_chat_id": None,
            "probe_chat_id": None,
            "live": False,
            "preseed_expected": False,
            "memory_pipeline": "preseeded_scope_retrieval",
            "readiness_profile": "already_preseeded",
            "config": sanitize_config_for_run(config),
            "side_effects": raw_records["side_effects"],
        },
        results=results,
        raw_records=raw_records,
    )
    return run_dir

def _optional_cli_text(value: str | None, option_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise BenchmarkError(f"{option_name} must not be empty")
    return normalized
