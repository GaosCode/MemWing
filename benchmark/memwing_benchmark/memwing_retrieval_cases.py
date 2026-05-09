from __future__ import annotations

from typing import Any

from memwing_benchmark.adapters.memwing import MemWingAdapter, memwing_case_scope
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluation import (
    MemorySearchOutcome,
    _evaluate_retrieval,
    _memory_search_raw,
    _result_from_eval,
)
from memwing_benchmark.evaluators.llm_judge import LlmJudge
from memwing_benchmark.metrics.retrieval import unique_preserve_order
from memwing_benchmark.memwing_retrieval_polling import (
    _details_from_poll,
    _poll_memwing_readiness,
    _require_memwing_real_search_components,
    _source_event_ids_from_results,
)
from memwing_benchmark.run_records import (
    MEMWING_FULL_DERIVED_READINESS_PROFILE,
    _text_list_from_mapping,
)
from memwing_benchmark.run_support import debug as _debug
from memwing_benchmark.schema import BenchmarkCase, NormalizedResult, TokenUsage, utc_now_iso


MEMWING_REAL_SEARCH_MAX_RESULTS = 20


def _run_memwing_preseeded_retrieval_batch(
    *,
    eval_run_id: str,
    source_run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    judge: LlmJudge,
    raw_records: dict[str, Any],
    limit: int,
) -> list[NormalizedResult]:
    results: list[NormalizedResult] = []
    for case in cases:
        scope = memwing_case_scope(
            config=adapter.config,
            run_id=source_run_id,
            case_id=case.case_id,
        )
        _debug(
            raw_records,
            "MemWing preseeded retrieval evaluate case 开始",
            case_id=case.case_id,
            source_run_id=source_run_id,
            project_memory_space_id=scope.project_memory_space_id,
            probe_count=len(case.probes),
        )
        for probe in case.probes:
            details = adapter.memory_search_details(
                probe.question,
                max_results=limit,
                scope=scope,
            )
            search_raw = _memory_search_raw(MemorySearchOutcome(details=details))
            raw_records.setdefault("memory_searches", []).append(
                {
                    "mode": "memwing_preseeded_retrieval",
                    "case_id": case.case_id,
                    "probe_id": probe.id,
                    "query": probe.question,
                    "source_run_id": source_run_id,
                    **search_raw,
                }
            )
            retrieval_result = _evaluate_retrieval(
                judge=judge,
                case=case,
                probe=probe,
                retrieved_contexts=details.contexts,
            )
            _debug(
                raw_records,
                "MemWing preseeded retrieval evaluate search 完成",
                case_id=case.case_id,
                probe_id=probe.id,
                result_count=len(details.results),
                latency_ms=details.latency_ms,
                recall_at_1=retrieval_result.retrieval.recall_at_1,
                recall_at_3=retrieval_result.retrieval.recall_at_3,
                recall_at_5=retrieval_result.retrieval.recall_at_5,
            )
            results.append(
                _result_from_eval(
                    run_id=eval_run_id,
                    backend=backend,
                    case=case,
                    probe=probe,
                    chat_id=None,
                    seed_message_ids=[item.id for item in case.expected_memory_items],
                    answer="",
                    retrieved_contexts=details.contexts,
                    retrieved_evidence_ids=_source_event_ids_from_results(details.results),
                    actual_tool_evidence_ids=[],
                    latency_ms=None,
                    tokens=TokenUsage(
                        available=False,
                        missing_reason="non-live MemWing preseeded retrieval evaluate run",
                    ),
                    memory_recall_latency_ms=details.latency_ms,
                    retrieval_result=retrieval_result,
                    answer_result=None,
                    raw={
                        "mode": "memwing_preseeded_retrieval",
                        "source_run_id": source_run_id,
                        **search_raw,
                    },
                )
            )
    return results

def _run_memwing_expected_preseed_retrieval_case(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    results: list[NormalizedResult],
    graph_mode: str,
) -> None:
    scope = memwing_case_scope(config=adapter.config, run_id=run_id, case_id=case.case_id)
    _debug(
        raw_records,
        "MemWing expected preseed retrieval case 开始",
        case_id=case.case_id,
        project_memory_space_id=scope.project_memory_space_id,
        expected_memory_count=len(case.expected_memory_items),
        probe_count=len(case.probes),
    )

    cleanup = adapter.cleanup_benchmark_scope(scope)
    raw_records.setdefault("memwing_scope_cleanup", []).append(
        {"case_id": case.case_id, "scope": scope.payload(), "response": cleanup}
    )

    preseed = adapter.preseed_expected_memories(
        case=case,
        run_id=run_id,
        scope=scope,
        graph_mode=graph_mode,
    )
    seed_completed_at = utc_now_iso()
    raw_records.setdefault("memwing_preseed_expected", []).append(
        {"case_id": case.case_id, "scope": scope.payload(), "response": preseed}
    )
    _debug(
        raw_records,
        "MemWing expected preseed 完成",
        case_id=case.case_id,
        source_event_count=preseed.get("source_event_count"),
        memory_item_count=preseed.get("memory_item_count"),
        page_memory_count=preseed.get("page_memory_count"),
        graph_episode_count=preseed.get("graph_episode_count"),
        graph_fact_count=preseed.get("graph_fact_count"),
    )

    expected_source_event_ids = _text_list_from_mapping(preseed, "source_event_ids")
    for probe in case.probes:
        _debug(
            raw_records,
            "MemWing expected preseed search 开始",
            case_id=case.case_id,
            probe_id=probe.id,
        )
        details = adapter.memory_search_details(
            probe.question,
            max_results=MEMWING_REAL_SEARCH_MAX_RESULTS,
            scope=scope,
        )
        search_raw = _memory_search_raw(MemorySearchOutcome(details=details))
        raw_records.setdefault("memory_searches", []).append(
            {
                "mode": "memwing_expected_preseed_retrieval",
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                **search_raw,
            }
        )
        retrieval_result = _evaluate_retrieval(
            judge=judge,
            case=case,
            probe=probe,
            retrieved_contexts=details.contexts,
        )
        _debug(
            raw_records,
            "MemWing expected preseed search 完成",
            case_id=case.case_id,
            probe_id=probe.id,
            result_count=len(details.results),
            latency_ms=details.latency_ms,
            recall_at_1=retrieval_result.retrieval.recall_at_1
            if retrieval_result
            else None,
            recall_at_3=retrieval_result.retrieval.recall_at_3
            if retrieval_result
            else None,
            recall_at_5=retrieval_result.retrieval.recall_at_5
            if retrieval_result
            else None,
        )
        results.append(
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=None,
                seed_message_ids=[item.id for item in case.expected_memory_items],
                answer="",
                retrieved_contexts=details.contexts,
                retrieved_evidence_ids=_source_event_ids_from_results(details.results),
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(
                    available=False,
                    missing_reason="non-live MemWing expected preseed retrieval run",
                ),
                memory_recall_latency_ms=details.latency_ms,
                retrieval_result=retrieval_result,
                answer_result=None,
                raw={
                    "mode": "memwing_expected_preseed_retrieval",
                    "seed_completed_at": seed_completed_at,
                    "expected_source_event_ids": expected_source_event_ids,
                    "preseed_expected": preseed,
                    **search_raw,
                },
            )
        )

def _run_memwing_real_ingest_retrieval_case(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    results: list[NormalizedResult],
) -> None:
    scope = memwing_case_scope(config=adapter.config, run_id=run_id, case_id=case.case_id)
    _debug(
        raw_records,
        "MemWing real ingest retrieval case 开始",
        case_id=case.case_id,
        project_memory_space_id=scope.project_memory_space_id,
        seed_message_count=len(case.seed_messages),
        probe_count=len(case.probes),
    )

    _debug(raw_records, "MemWing benchmark scope cleanup 开始", case_id=case.case_id)
    cleanup = adapter.cleanup_benchmark_scope(scope)
    raw_records.setdefault("memwing_scope_cleanup", []).append(
        {"case_id": case.case_id, "scope": scope.payload(), "response": cleanup}
    )
    _debug(raw_records, "MemWing benchmark scope cleanup 完成", case_id=case.case_id)

    _debug(raw_records, "MemWing benchmark ingest 开始", case_id=case.case_id)
    ingest_records = adapter.ingest_seed_messages(case=case, run_id=run_id, scope=scope)
    seed_completed_at = utc_now_iso()
    raw_records.setdefault("memwing_ingest", []).extend(ingest_records)
    _debug(
        raw_records,
        "MemWing benchmark ingest 完成",
        case_id=case.case_id,
        accepted_count=sum(1 for record in ingest_records if record.get("accepted") is True),
    )

    expected_source_event_ids = _expected_source_event_ids_for_real_ingest(
        case=case,
        ingest_records=ingest_records,
    )
    _debug(
        raw_records,
        "MemWing product pipeline await 开始",
        case_id=case.case_id,
        expected_source_event_count=len(expected_source_event_ids),
    )
    drain = adapter.drain_benchmark_pipeline(
        scope,
        max_rounds=50,
        batch_size=max(10, len(expected_source_event_ids)),
    )
    raw_records.setdefault("memwing_pipeline_drains", []).append(
        {
            "case_id": case.case_id,
            "scope": scope.payload(),
            "response": drain,
        }
    )
    if drain.get("drained") is not True:
        raise BenchmarkError(f"MemWing pipeline drain did not finish: case_id={case.case_id}")
    readiness = adapter.pipeline_await(
        scope=scope,
        source_event_ids=expected_source_event_ids,
        profile=MEMWING_FULL_DERIVED_READINESS_PROFILE,
    )
    raw_records.setdefault("memwing_pipeline_awaits", []).append(
        {
            "case_id": case.case_id,
            "scope": scope.payload(),
            "profile": MEMWING_FULL_DERIVED_READINESS_PROFILE,
            "response": readiness,
        }
    )
    if readiness.get("ready") is not True:
        raise BenchmarkError(f"MemWing pipeline await did not become ready: case_id={case.case_id}")
    _debug(raw_records, "MemWing product pipeline await 完成", case_id=case.case_id)

    for probe in case.probes:
        _debug(
            raw_records,
            "MemWing benchmark search 开始",
            case_id=case.case_id,
            probe_id=probe.id,
        )
        details = adapter.memory_search_details(
            probe.question,
            max_results=MEMWING_REAL_SEARCH_MAX_RESULTS,
            scope=scope,
        )
        _debug(
            raw_records,
            "MemWing benchmark search 完成",
            case_id=case.case_id,
            probe_id=probe.id,
            result_count=len(details.results),
            latency_ms=details.latency_ms,
        )
        search_raw = _memory_search_raw(MemorySearchOutcome(details=details))
        _require_memwing_real_search_components(
            search_raw=search_raw,
            case_id=case.case_id,
            probe_id=probe.id,
        )
        raw_records.setdefault("memory_searches", []).append(
            {
                "mode": "memwing_real_ingest_retrieval",
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                **search_raw,
            }
        )
        retrieval_result = _evaluate_retrieval(
            judge=judge,
            case=case,
            probe=probe,
            retrieved_contexts=details.contexts,
        )
        results.append(
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_contexts=details.contexts,
                retrieved_evidence_ids=_source_event_ids_from_results(details.results),
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(
                    available=False,
                    missing_reason="non-live MemWing retrieval run",
                ),
                memory_recall_latency_ms=details.latency_ms,
                retrieval_result=retrieval_result,
                answer_result=None,
                raw={
                    "mode": "memwing_real_ingest_retrieval",
                    "seed_completed_at": seed_completed_at,
                    "expected_source_event_ids": expected_source_event_ids,
                    "readiness": readiness,
                    **search_raw,
                },
            )
        )

def _expected_source_event_ids_for_real_ingest(
    *,
    case: BenchmarkCase,
    ingest_records: list[dict[str, Any]],
) -> list[str]:
    source_event_ids = [
        source_event_id
        for record in ingest_records
        if isinstance(source_event_id := record.get("source_event_id"), str)
    ]
    if source_event_ids:
        return unique_preserve_order(source_event_ids)
    return [message.id for message in case.seed_messages]

def _run_memwing_retrieval_case(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    poll_interval_seconds: float,
    timeout_seconds: float,
    ingest_seed_events: bool,
    results: list[NormalizedResult],
) -> None:
    _debug(
        raw_records,
        "MemWing retrieval case 开始",
        case_id=case.case_id,
        seed_message_count=len(case.seed_messages),
        probe_count=len(case.probes),
    )
    ingest_records = (
        adapter.ingest_seed_messages(case=case, run_id=run_id) if ingest_seed_events else []
    )
    seed_completed_at = utc_now_iso()
    raw_records.setdefault("memwing_ingest", []).extend(ingest_records)
    source_event_ids_by_seed = {
        record["seed_message_id"]: record["source_event_id"]
        for record in ingest_records
        if isinstance(record.get("seed_message_id"), str)
        and isinstance(record.get("source_event_id"), str)
    }

    for probe in case.probes:
        expected_source_event_ids = (
            [
                source_event_ids_by_seed[evidence_id]
                for evidence_id in probe.gold_evidence_ids
                if evidence_id in source_event_ids_by_seed
            ]
            or [
                source_event_id
                for source_event_id in source_event_ids_by_seed.values()
                if source_event_id
            ]
            or ([] if ingest_seed_events else list(probe.gold_evidence_ids))
        )
        poll = _poll_memwing_readiness(
            adapter=adapter,
            query=probe.question,
            expected_source_event_ids=expected_source_event_ids,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            raw_records=raw_records,
            case_id=case.case_id,
            probe_id=probe.id,
        )
        raw_records.setdefault("memwing_polls", []).append(
            {
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                "expected_source_event_ids": expected_source_event_ids,
                "attempts": poll.attempts,
                "durable_memory_available": poll.durable_memory_available,
                "extraction_timeout": poll.extraction_timeout,
                "first_memory_available_at": poll.first_memory_available_at,
            }
        )
        poll_details = _details_from_poll(poll)
        search_raw = _memory_search_raw(
            MemorySearchOutcome(details=poll_details, error=poll.search_error)
        )
        raw_records.setdefault("memory_searches", []).append(
            {
                "mode": "memwing_retrieval",
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                **search_raw,
            }
        )
        retrieval_result = _evaluate_retrieval(
            judge=judge,
            case=case,
            probe=probe,
            retrieved_contexts=poll.retrieved_contexts,
        )
        results.append(
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_contexts=poll.retrieved_contexts,
                retrieved_evidence_ids=_source_event_ids_from_results(poll_details.results),
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(
                    available=False,
                    missing_reason="non-live MemWing retrieval run",
                ),
                memory_recall_latency_ms=None,
                retrieval_result=retrieval_result,
                answer_result=None,
                raw={
                    "mode": "memwing_retrieval",
                    "seed_completed_at": seed_completed_at,
                    "first_memory_available_at": poll.first_memory_available_at,
                    "durable_memory_available": poll.durable_memory_available,
                    "extraction_timeout": poll.extraction_timeout,
                    "memory_poll_attempts": poll.attempts,
                    "expected_source_event_ids": expected_source_event_ids,
                    **search_raw,
                },
            )
        )
