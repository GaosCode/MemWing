from __future__ import annotations

from pathlib import Path
from typing import Any

from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.evaluation import (
    _evaluate_retrieval,
    _memory_search_raw,
    _result_from_eval,
    _safe_memory_search,
)
from memwing_benchmark.evaluators.llm_judge import LlmJudge
from memwing_benchmark.run_support import confirm_side_effect as _confirm_side_effect
from memwing_benchmark.run_support import debug as _debug
from memwing_benchmark.schema import (
    BenchmarkCase,
    NormalizedResult,
    TokenUsage,
    iter_case_probes,
)


def _run_offline(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    yes: bool,
) -> list[NormalizedResult]:
    if judge is None:
        _debug(
            raw_records,
            "离线检索跳过：judge api key unavailable",
            case_count=len(cases),
            probe_count=sum(len(case.probes) for case in cases),
        )
        return [
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=config.feishu.chat_id or None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_contexts=[],
                retrieved_evidence_ids=[],
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(available=False, missing_reason="judge api key unavailable"),
                memory_recall_latency_ms=None,
                retrieval_result=None,
                answer_result=None,
                raw={"mode": "offline", "missing_reason": "judge api key unavailable"},
            )
            for case, probe in iter_case_probes(cases)
        ]

    if any(case.seed_messages for case in cases):
        _debug(
            raw_records,
            "准备写入离线 preseed 并重建 OpenClaw memory index",
            case_count=len(cases),
            seed_message_count=sum(len(case.seed_messages) for case in cases),
        )
        _confirm_side_effect("向 OpenClaw workspace 写入 benchmark preseed memory 并重建索引", yes)
    preseed_path = adapter.preseed_long_term_memories(cases=cases, run_id=run_id)
    if preseed_path:
        _debug(raw_records, "离线 preseed 写入完成", path=str(preseed_path))
        raw_records["side_effects"].append(
            {"action": "preseed_openclaw_memory", "path": str(preseed_path)}
        )
    else:
        _debug(raw_records, "离线 preseed 无可写入内容", case_count=len(cases))

    results: list[NormalizedResult] = []
    for case, probe in iter_case_probes(cases):
        _debug(
            raw_records,
            "离线检索开始",
            case_id=case.case_id,
            probe_id=probe.id,
            query=probe.question,
        )
        search = _safe_memory_search(adapter, probe.question)
        search_raw = _memory_search_raw(search)
        _debug(
            raw_records,
            "离线检索完成",
            case_id=case.case_id,
            probe_id=probe.id,
            result_count=search_raw["memory_search_result_count"],
            latency_ms=search_raw["memory_search_latency_ms"],
            top_score=search_raw["memory_search_top_score"],
            top_path=search_raw["memory_search_top_path"],
            error=search.error,
        )
        raw_records.setdefault("memory_searches", []).append(
            {
                "mode": "offline",
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                **search_raw,
            }
        )
        retrieved_contexts = search.details.contexts
        retrieval_result = _evaluate_retrieval(
            judge=judge,
            case=case,
            probe=probe,
            retrieved_contexts=retrieved_contexts,
        )
        _debug(
            raw_records,
            "离线检索 judge 完成",
            case_id=case.case_id,
            probe_id=probe.id,
            recall_at_1=retrieval_result.retrieval.recall_at_1
            if retrieval_result
            else None,
            recall_at_3=retrieval_result.retrieval.recall_at_3
            if retrieval_result
            else None,
            recall_at_5=retrieval_result.retrieval.recall_at_5
            if retrieval_result
            else None,
            matched_gold_memory_ids=retrieval_result.retrieval.matched_gold_memory_ids
            if retrieval_result
            else [],
        )
        results.append(
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=config.feishu.chat_id or None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_contexts=retrieved_contexts,
                retrieved_evidence_ids=[],
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(available=False, missing_reason="non-live run"),
                memory_recall_latency_ms=None,
                retrieval_result=retrieval_result,
                answer_result=None,
                raw={
                    "mode": "offline",
                    **search_raw,
                },
            )
        )
    return results

def _run_offline_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    run_dir: Path,
    yes: bool,
) -> list[NormalizedResult]:
    del run_dir
    if judge is None:
        _debug(
            raw_records,
            "离线批量跳过：judge api key unavailable",
            case_count=len(cases),
        )
        return _run_offline(
            run_id=run_id,
            backend=backend,
            cases=cases,
            config=config,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            yes=yes,
        )

    _confirm_side_effect(
        "在当前 OpenClaw 默认 workspace 中按 case 写入对应 preseed memory 并重建索引",
        yes,
    )
    workspace = adapter.get_default_workspace()
    _debug(raw_records, "离线批量使用 OpenClaw 默认 workspace", workspace=workspace)
    results: list[NormalizedResult] = []
    raw_records["side_effects"].append(
        {"action": "use_default_openclaw_workspace_for_offline_batch", "workspace": workspace}
    )
    for case in cases:
        _debug(raw_records, "离线批量 case 开始", case_id=case.case_id, workspace=workspace)
        case_results = _run_offline(
            run_id=run_id,
            backend=backend,
            cases=[case],
            config=config,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            yes=True,
        )
        results.extend(case_results)
        _debug(
            raw_records,
            "离线批量 case 完成",
            case_id=case.case_id,
            probe_count=len(case.probes),
            result_count=len(case_results),
        )
        raw_records["side_effects"].append(
            {
                "action": "offline_batch_case_completed",
                "case_id": case.case_id,
                "workspace": workspace,
            }
        )
    return results
