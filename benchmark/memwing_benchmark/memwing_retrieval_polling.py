from __future__ import annotations

import time
from typing import Any

from memwing_benchmark.adapters.memwing import MemWingAdapter
from memwing_benchmark.adapters.openclaw_native import MemorySearchDetails
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluation import DurablePollResult, _memory_search_raw, _safe_memory_search
from memwing_benchmark.metrics.retrieval import unique_preserve_order
from memwing_benchmark.run_records import _optional_int
from memwing_benchmark.run_support import debug as _debug
from memwing_benchmark.schema import utc_now_iso


def _poll_memwing_readiness(
    *,
    adapter: MemWingAdapter,
    query: str,
    expected_source_event_ids: list[str],
    poll_interval_seconds: float,
    timeout_seconds: float,
    raw_records: dict[str, Any] | None = None,
    case_id: str | None = None,
    probe_id: str | None = None,
) -> DurablePollResult:
    deadline = time.monotonic() + timeout_seconds
    attempts: list[dict[str, Any]] = []
    last_details = MemorySearchDetails(contexts=[], results=[], latency_ms=0, raw=None)
    last_error: str | None = None

    while True:
        attempted_at = utc_now_iso()
        search = _safe_memory_search(adapter, query)
        details = search.details
        retrieved_source_event_ids = _source_event_ids_from_results(details.results)
        matched_source_event_ids = [
            source_event_id
            for source_event_id in expected_source_event_ids
            if source_event_id in retrieved_source_event_ids
        ]
        hit = bool(expected_source_event_ids and matched_source_event_ids)
        attempts.append(
            {
                "attempted_at": attempted_at,
                "expected_source_event_ids": expected_source_event_ids,
                "retrieved_source_event_ids": retrieved_source_event_ids,
                "matched_source_event_ids": matched_source_event_ids,
                **_memory_search_raw(search),
                "durable_memory_available": hit,
            }
        )
        if raw_records is not None:
            _debug(
                raw_records,
                "MemWing readiness poll attempt",
                case_id=case_id,
                probe_id=probe_id,
                attempt_count=len(attempts),
                expected_source_event_count=len(expected_source_event_ids),
                retrieved_source_event_count=len(retrieved_source_event_ids),
                matched_source_event_ids=matched_source_event_ids,
                result_count=len(details.results),
                latency_ms=details.latency_ms,
                memory_search_error=search.error,
                durable_memory_available=hit,
            )
        last_details = details
        last_error = search.error
        if hit:
            return DurablePollResult(
                retrieved_contexts=details.contexts,
                search_error=search.error,
                retrieval_result=None,
                first_memory_available_at=attempted_at,
                durable_memory_available=True,
                extraction_timeout=False,
                attempts=attempts,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return DurablePollResult(
                retrieved_contexts=last_details.contexts,
                search_error=last_error,
                retrieval_result=None,
                first_memory_available_at=None,
                durable_memory_available=False,
                extraction_timeout=True,
                attempts=attempts,
            )
        sleep_seconds = min(poll_interval_seconds, remaining)
        if raw_records is not None:
            _debug(
                raw_records,
                "等待 MemWing readiness poll",
                case_id=case_id,
                probe_id=probe_id,
                seconds=round(sleep_seconds, 3),
                remaining_seconds=round(max(remaining, 0), 3),
            )
        time.sleep(sleep_seconds)

def _details_from_poll(poll: DurablePollResult) -> MemorySearchDetails:
    if not poll.attempts:
        return MemorySearchDetails(contexts=[], results=[], latency_ms=0, raw=None)
    last_raw = poll.attempts[-1]
    results = last_raw.get("memory_search_results")
    raw = last_raw.get("memory_search_raw")
    return MemorySearchDetails(
        contexts=poll.retrieved_contexts,
        results=results if isinstance(results, list) else [],
        latency_ms=_optional_int(last_raw.get("memory_search_latency_ms")) or 0,
        raw=raw if isinstance(raw, dict) else None,
    )

def _source_event_ids_from_results(results: list[dict[str, Any]]) -> list[str]:
    source_event_ids: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        raw_ids = result.get("source_event_ids")
        if isinstance(raw_ids, list):
            source_event_ids.extend(item for item in raw_ids if isinstance(item, str))
    return unique_preserve_order(source_event_ids)

def _require_memwing_real_search_components(
    *,
    search_raw: dict[str, Any],
    case_id: str,
    probe_id: str,
) -> None:
    error = search_raw.get("memory_search_error")
    if isinstance(error, str) and error:
        raise BenchmarkError(
            "MemWing real pipeline search failed: "
            f"case_id={case_id} probe_id={probe_id} error={error}"
        )
    warnings = search_raw.get("memory_search_warnings")
    if isinstance(warnings, list) and warnings:
        raise BenchmarkError(
            "MemWing real pipeline search returned backend warnings: "
            f"case_id={case_id} probe_id={probe_id}"
        )
    source_mix = search_raw.get("memory_search_source_mix")
    if not isinstance(source_mix, dict):
        source_mix = {}
    derived_hits = sum(
        source_mix.get(source, 0)
        for source in ("graph_backend", "evidence_index")
        if isinstance(source_mix.get(source), int)
    )
    if derived_hits <= 0:
        raise BenchmarkError(
            "MemWing real pipeline search did not return graph or evidence results: "
            f"case_id={case_id} probe_id={probe_id}"
        )
