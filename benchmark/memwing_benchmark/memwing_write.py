from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from memwing_benchmark.adapters.memwing import (
    MemWingAdapter,
    memwing_case_scope,
)
from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluation import (
    MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
    _evaluate_write,
    _expected_memories,
    _expected_memories_for_other_cases,
    _memwing_write_scored_contexts,
    _memory_search_raw,
    _noise_memories,
    _result_from_memwing_write,
    _result_from_write_ingest,
    _safe_memory_search,
    _write_quality_ratios,
)
from memwing_benchmark.evaluators.llm_judge import LlmJudge
from memwing_benchmark.live_workspace import LiveChatIds
from memwing_benchmark.metrics.retrieval import unique_preserve_order
from memwing_benchmark.memwing_retrieval import (
    MEMWING_REAL_SEARCH_MAX_RESULTS,
    _require_memwing_real_search_components,
)
from memwing_benchmark.openclaw_native_runs import (
    _require_openclaw_plugin_tool_evidence,
    _run_write_ingest_batch,
)
from memwing_benchmark.memwing_write_records import (
    MemWingWriteIngestRecord,
    _await_memwing_write_evaluate_readiness,
    _load_memwing_write_ingest_records,
)
from memwing_benchmark.run_records import _record_memwing_http_records
from memwing_benchmark.run_support import confirm_side_effect as _confirm_side_effect
from memwing_benchmark.run_support import debug as _debug
from memwing_benchmark.schema import BenchmarkCase, NormalizedResult, utc_now_iso


__all__ = [
    "MemWingWriteIngestRecord",
    "_await_memwing_write_evaluate_readiness",
    "_load_memwing_write_ingest_records",
    "_poll_memwing_write_readiness",
    "_run_memwing_openclaw_plugin_write_ingest_batch",
    "_run_memwing_write_evaluate_batch",
    "_run_memwing_write_ingest_batch",
]


def _run_memwing_write_ingest_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    raw_records: dict[str, Any],
    yes: bool,
) -> list[NormalizedResult]:
    if any(case.seed_messages for case in cases):
        _confirm_side_effect("向 MemWing HTTP ingest endpoint 写入 benchmark Source Events", yes)

    results: list[NormalizedResult] = []
    for case in cases:
        scope = memwing_case_scope(config=adapter.config, run_id=run_id, case_id=case.case_id)
        _debug(
            raw_records,
            "MemWing write ingest case 开始",
            case_id=case.case_id,
            seed_message_count=len(case.seed_messages),
            project_memory_space_id=scope.project_memory_space_id,
        )
        _debug(raw_records, "MemWing write ingest benchmark scope cleanup 开始", case_id=case.case_id)
        cleanup = adapter.cleanup_benchmark_scope(scope)
        raw_records.setdefault("memwing_scope_cleanup", []).append(
            {"case_id": case.case_id, "scope": scope.payload(), "response": cleanup}
        )
        _debug(raw_records, "MemWing write ingest benchmark scope cleanup 完成", case_id=case.case_id)

        ingest_records = adapter.ingest_seed_messages(case=case, run_id=run_id, scope=scope)
        seed_completed_at = utc_now_iso()
        raw_records.setdefault("memwing_ingest", []).extend(ingest_records)
        raw_records.setdefault("memory_writes", []).append(
            {
                "phase": "ingest",
                "backend": backend,
                "case_id": case.case_id,
                "seed_message_count": len(case.seed_messages),
                "accepted_count": sum(1 for record in ingest_records if record.get("accepted") is True),
                "scope": scope.payload(),
                "source_event_ids": [
                    record["source_event_id"]
                    for record in ingest_records
                    if isinstance(record.get("source_event_id"), str)
                ],
                "note": "MemWing ingest sends Source Events through the HTTP adapter; run --mode write --phase evaluate after indexing settles.",
            }
        )
        results.append(
            _result_from_write_ingest(
                run_id=run_id,
                backend=backend,
                case=case,
                chat_id=None,
                seed_message_ids=[message.id for message in case.seed_messages],
                seed_completed_at=seed_completed_at,
                raw_extra={
                    "backend": backend,
                    "ingest_records": ingest_records,
                },
                observability_note=(
                    "MemWing write ingest sends Source Events through HTTP; evaluate after indexing settles."
                ),
            )
        )
    return results

def _run_memwing_write_evaluate_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    runs_root: Path,
    ingest_run_id: str | None = None,
) -> list[NormalizedResult]:
    results: list[NormalizedResult] = []
    total_cases = len(cases)
    ingest_records = _load_memwing_write_ingest_records(
        runs_root=runs_root,
        backend=backend,
        adapter=adapter,
        case_ids=[case.case_id for case in cases],
        ingest_run_id=ingest_run_id,
    )
    for index, case in enumerate(cases, start=1):
        expected_memories = _expected_memories(case)
        noise_memories = _noise_memories(case)
        allowed_other_memories = _expected_memories_for_other_cases(cases, case.case_id)
        ingest_record = ingest_records.get(case.case_id)
        _debug(
            raw_records,
            "MemWing write evaluate case 开始",
            case_id=case.case_id,
            case_index=index,
            case_count=total_cases,
            expected_memory_count=len(expected_memories),
            noise_memory_count=len(noise_memories),
            allowed_other_memory_count=len(allowed_other_memories),
            source_event_count=len(ingest_record.source_event_ids) if ingest_record is not None else 0,
            requested_ingest_run_id=ingest_run_id,
            selected_ingest_run_id=ingest_record.run_id if ingest_record is not None else None,
        )
        readiness_summary = _await_memwing_write_evaluate_readiness(
            adapter=adapter,
            case=case,
            ingest_record=ingest_record,
            raw_records=raw_records,
            runs_root=runs_root,
            requested_ingest_run_id=ingest_run_id,
        )
        searches: list[dict[str, Any]] = []
        written_contexts: list[str] = []
        scored_written_contexts: list[str] = []
        search_latencies: list[int] = []
        search_errors: list[str] = []
        for item in case.expected_memory_items:
            search = _safe_memory_search(
                adapter,
                item.fact,
                max_results=MEMWING_REAL_SEARCH_MAX_RESULTS,
                scope=ingest_record.scope,
            )
            search_raw = _memory_search_raw(search)
            _require_memwing_real_search_components(
                search_raw=search_raw,
                case_id=case.case_id,
                probe_id=item.id,
            )
            if search.error:
                search_errors.append(search.error)
            search_latencies.append(search.details.latency_ms)
            written_contexts.extend(search.details.contexts)
            scored_written_contexts.extend(_memwing_write_scored_contexts(search.details))
            searches.append(
                {
                    "case_id": case.case_id,
                    "expected_memory_id": item.id,
                    "query": item.fact,
                    **search_raw,
                }
            )
            raw_records.setdefault("memory_searches", []).append(
                {
                    "mode": "memwing_write_evaluate",
                    "case_id": case.case_id,
                    "expected_memory_id": item.id,
                    "query": item.fact,
                    **search_raw,
                }
            )
        written_contexts = unique_preserve_order(written_contexts)
        scored_written_contexts = unique_preserve_order(scored_written_contexts)
        _debug(
            raw_records,
            "MemWing write evaluate search 完成",
            case_id=case.case_id,
            written_context_count=len(written_contexts),
            scored_context_count=len(scored_written_contexts),
            excluded_raw_context_count=max(0, len(written_contexts) - len(scored_written_contexts)),
            search_error_count=len(search_errors),
        )
        write_result = _evaluate_write(
            judge=judge,
            case_id=case.case_id,
            expected_memories=expected_memories,
            noise_memories=noise_memories,
            written_contexts=scored_written_contexts,
            allowed_other_memories=allowed_other_memories,
        )
        write_ratios = _write_quality_ratios(write_result)
        raw_records.setdefault("memory_writes", []).append(
            {
                "phase": "evaluate",
                "backend": backend,
                "case_id": case.case_id,
                "searches": searches,
                "written_context_count": len(written_contexts),
                "scored_written_context_count": len(scored_written_contexts),
                "excluded_raw_context_count": max(
                    0,
                    len(written_contexts) - len(scored_written_contexts),
                ),
                "scored_written_contexts": scored_written_contexts,
                "changed_file_metrics_available": False,
                "changed_file_metrics_missing_reason": MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
                "readiness": readiness_summary,
                "selected_ingest_run_id": ingest_record.run_id if ingest_record is not None else None,
                "selected_ingest_run_dir": str(ingest_record.run_dir) if ingest_record is not None else None,
                "source_event_ids": ingest_record.source_event_ids if ingest_record is not None else [],
                "write_judge": write_result.model_dump(mode="json") if write_result else None,
                "write_quality_ratios": write_ratios,
            }
        )
        results.append(
            _result_from_memwing_write(
                run_id=run_id,
                backend=backend,
                case=case,
                seed_message_ids=[message.id for message in case.seed_messages],
                written_contexts=written_contexts,
                search_latencies=search_latencies,
                search_errors=search_errors,
                write_result=write_result,
                searches=searches,
                readiness_summary=readiness_summary,
                scored_context_count=len(scored_written_contexts),
            )
        )
    return results


def _run_memwing_openclaw_plugin_write_ingest_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    openclaw_adapter: OpenClawNativeAdapter,
    memwing_adapter: MemWingAdapter,
    chats: LiveChatIds,
    raw_records: dict[str, Any],
    message_interval_seconds: float,
) -> list[NormalizedResult]:
    results = _run_write_ingest_batch(
        run_id=run_id,
        backend=backend,
        cases=cases,
        config=config,
        adapter=openclaw_adapter,
        chats=chats,
        raw_records=raw_records,
        message_interval_seconds=message_interval_seconds,
    )
    _require_openclaw_plugin_tool_evidence(
        config=config,
        adapter=openclaw_adapter,
        raw_records=raw_records,
    )
    for case in cases:
        poll = _poll_memwing_write_readiness(
            adapter=memwing_adapter,
            case=case,
            raw_records=raw_records,
            poll_interval_seconds=config.memwing.poll_interval_seconds,
            timeout_seconds=config.memwing.poll_timeout_seconds,
        )
        raw_records.setdefault("memwing_polls", []).append(
            {
                "mode": "memwing_openclaw_plugin_write_ingest",
                "case_id": case.case_id,
                **poll,
            }
        )
    _record_memwing_http_records(raw_records, memwing_adapter.records, openclaw_plugin=True)
    return results

def _poll_memwing_write_readiness(
    *,
    adapter: MemWingAdapter,
    case: BenchmarkCase,
    raw_records: dict[str, Any],
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    if poll_interval_seconds <= 0:
        raise BenchmarkError("memwing.poll_interval_seconds must be greater than 0")
    if timeout_seconds < 0:
        raise BenchmarkError("memwing.poll_timeout_seconds must be greater than or equal to 0")
    deadline = time.monotonic() + timeout_seconds
    attempts: list[dict[str, Any]] = []
    expected_items = list(case.expected_memory_items)
    if not expected_items:
        return {
            "attempts": attempts,
            "durable_memory_available": None,
            "extraction_timeout": False,
            "first_memory_available_at": None,
        }

    while True:
        attempted_at = utc_now_iso()
        searches: list[dict[str, Any]] = []
        matched_ids: list[str] = []
        for item in expected_items:
            search = _safe_memory_search(adapter, item.fact)
            search_raw = _memory_search_raw(search)
            hit = bool(search.details.contexts)
            if hit:
                matched_ids.append(item.id)
            row = {
                "mode": "memwing_openclaw_plugin_write_ingest",
                "case_id": case.case_id,
                "expected_memory_id": item.id,
                "query": item.fact,
                "durable_memory_available": hit,
                **search_raw,
            }
            searches.append(row)
            raw_records.setdefault("memory_searches", []).append(row)

        available = len(matched_ids) == len(expected_items)
        attempts.append(
            {
                "attempted_at": attempted_at,
                "matched_expected_memory_ids": matched_ids,
                "expected_memory_ids": [item.id for item in expected_items],
                "searches": searches,
                "durable_memory_available": available,
            }
        )
        _debug(
            raw_records,
            "MemWing write readiness poll attempt",
            case_id=case.case_id,
            attempt_count=len(attempts),
            matched_expected_memory_ids=matched_ids,
            expected_memory_count=len(expected_items),
            durable_memory_available=available,
        )
        if available:
            return {
                "attempts": attempts,
                "durable_memory_available": True,
                "extraction_timeout": False,
                "first_memory_available_at": attempted_at,
            }
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "attempts": attempts,
                "durable_memory_available": False,
                "extraction_timeout": True,
                "first_memory_available_at": None,
            }
        sleep_seconds = min(poll_interval_seconds, remaining)
        _debug(
            raw_records,
            "等待 MemWing write readiness poll",
            case_id=case.case_id,
            seconds=round(sleep_seconds, 3),
            remaining_seconds=round(max(remaining, 0), 3),
        )
        time.sleep(sleep_seconds)
