from __future__ import annotations

from typing import Any

from memwing_benchmark.adapters.memwing import MemWingAdapter
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluators.llm_judge import LlmJudge
from memwing_benchmark.memwing_retrieval_cases import (
    _run_memwing_expected_preseed_retrieval_case,
    _run_memwing_preseeded_retrieval_batch,
    _run_memwing_real_ingest_retrieval_case,
    _run_memwing_retrieval_case,
)
from memwing_benchmark.memwing_retrieval_polling import (
    _details_from_poll,
    _poll_memwing_readiness,
    _require_memwing_real_search_components,
    _source_event_ids_from_results,
)
from memwing_benchmark.run_support import confirm_side_effect as _confirm_side_effect
from memwing_benchmark.schema import BenchmarkCase, NormalizedResult


MEMWING_REAL_SEARCH_MAX_RESULTS = 20

__all__ = [
    "MEMWING_REAL_SEARCH_MAX_RESULTS",
    "_details_from_poll",
    "_poll_memwing_readiness",
    "_require_memwing_real_search_components",
    "_run_memwing_expected_preseed_retrieval_batch",
    "_run_memwing_expected_preseed_retrieval_case",
    "_run_memwing_preseeded_retrieval_batch",
    "_run_memwing_real_ingest_retrieval_batch",
    "_run_memwing_real_ingest_retrieval_case",
    "_run_memwing_retrieval_batch",
    "_run_memwing_retrieval_case",
    "_source_event_ids_from_results",
]


def _run_memwing_retrieval_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    poll_interval_seconds: float,
    timeout_seconds: float,
    yes: bool,
    ingest_seed_events: bool = True,
    config: Any | None = None,
    pg_preseed_per_case: bool = False,
    preseed_expected: bool = False,
    preseed_graph_mode: str = "direct_neo4j",
    pg_cleanup_cases: list[BenchmarkCase] | None = None,
) -> list[NormalizedResult]:
    if poll_interval_seconds <= 0:
        raise BenchmarkError("memwing.poll_interval_seconds must be greater than 0")
    if timeout_seconds < 0:
        raise BenchmarkError("memwing.poll_timeout_seconds must be greater than or equal to 0")
    if ingest_seed_events and any(case.seed_messages for case in cases):
        _confirm_side_effect("向 MemWing HTTP ingest endpoint 写入 benchmark Source Events", yes)
    if preseed_expected:
        _confirm_side_effect(
            "清理每个 benchmark case scope，并通过 MemWing admin preseed-expected "
            "写入 expected memory_items、direct graph preseed 和 page_memory",
            yes,
        )
        return _run_memwing_expected_preseed_retrieval_batch(
            run_id=run_id,
            backend=backend,
            cases=cases,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            graph_mode=preseed_graph_mode,
        )
    if pg_preseed_per_case:
        _confirm_side_effect(
            "通过 MemWing HTTP/OpenClaw ingest endpoint 写入 benchmark Source Events，"
            "并按 case scope 执行 cleanup 和 product pipeline await",
            yes,
        )
        return _run_memwing_real_ingest_retrieval_batch(
            run_id=run_id,
            backend=backend,
            cases=cases,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
        )

    results: list[NormalizedResult] = []
    for case in cases:
        _run_memwing_retrieval_case(
            run_id=run_id,
            backend=backend,
            case=case,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            ingest_seed_events=ingest_seed_events,
            results=results,
        )
    return results

def _run_memwing_real_ingest_retrieval_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
) -> list[NormalizedResult]:
    results: list[NormalizedResult] = []
    for case in cases:
        _run_memwing_real_ingest_retrieval_case(
            run_id=run_id,
            backend=backend,
            case=case,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            results=results,
        )
    return results

def _run_memwing_expected_preseed_retrieval_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    graph_mode: str,
) -> list[NormalizedResult]:
    results: list[NormalizedResult] = []
    for case in cases:
        _run_memwing_expected_preseed_retrieval_case(
            run_id=run_id,
            backend=backend,
            case=case,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            results=results,
            graph_mode=graph_mode,
        )
    return results

