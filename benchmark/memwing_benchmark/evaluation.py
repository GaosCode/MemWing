from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memwing_benchmark.adapters.memwing import MemWingCaseScope
from memwing_benchmark.adapters.openclaw_native import MemorySearchDetails
from memwing_benchmark.evaluation_results import (
    MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
    _result_from_eval,
    _result_from_memwing_write,
    _result_from_write,
    _result_from_write_ingest,
    _write_quality_ratios,
)
from memwing_benchmark.evaluators.llm_judge import JudgeResult, LlmJudge
from memwing_benchmark.metrics.retrieval import unique_preserve_order
from memwing_benchmark.models.volcengine_ark import VolcengineArkChatModel
from memwing_benchmark.run_records import _current_truth_branch_timings
from memwing_benchmark.schema import BenchmarkCase, GoldMemory, Probe


MEMWING_WRITE_RAW_SOURCES = frozenset({"evidence_index", "raw_events", "working_memory"})

__all__ = [
    "DurablePollResult",
    "MEMWING_CHANGED_FILE_METRICS_MISSING_REASON",
    "MemorySearchOutcome",
    "_build_judge",
    "_evaluate_answer",
    "_evaluate_retrieval",
    "_evaluate_write",
    "_expected_memories",
    "_expected_memories_for_other_cases",
    "_gold_memories",
    "_memory_search_raw",
    "_memwing_write_scored_contexts",
    "_noise_memories",
    "_result_from_eval",
    "_result_from_memwing_write",
    "_result_from_write",
    "_result_from_write_ingest",
    "_retrieval_hit",
    "_safe_memory_search",
    "_source_mix",
    "_write_quality_ratios",
]


@dataclass(frozen=True)
class DurablePollResult:
    retrieved_contexts: list[str]
    search_error: str | None
    retrieval_result: JudgeResult | None
    first_memory_available_at: str | None
    durable_memory_available: bool
    extraction_timeout: bool
    attempts: list[dict[str, Any]]

@dataclass(frozen=True)
class MemorySearchOutcome:
    details: MemorySearchDetails
    error: str | None = None


def _build_judge(config) -> LlmJudge | None:
    if not config.judge.has_api_key:
        return None
    if config.judge.provider != "volcengine_ark":
        return None
    model = VolcengineArkChatModel(
        api_key=config.judge.api_key,
        base_url=config.judge.base_url,
        model=config.judge.model,
    )
    return LlmJudge(model, temperature=config.judge.temperature)

def _evaluate_retrieval(
    *,
    judge: LlmJudge | None,
    case: BenchmarkCase,
    probe: Probe,
    retrieved_contexts: list[str],
) -> JudgeResult | None:
    if judge is None:
        return None
    return judge.evaluate_retrieval(
        case_id=case.case_id,
        probe=probe,
        gold_memories=_gold_memories(case, probe.gold_evidence_ids),
        old_memories=_gold_memories(case, probe.old_evidence_ids),
        retrieved_context=retrieved_contexts,
    )

def _retrieval_hit(result: JudgeResult | None) -> bool:
    if result is None:
        return False
    retrieval = result.retrieval
    return bool(retrieval.recall_at_1 or retrieval.recall_at_3 or retrieval.recall_at_5)

def _evaluate_answer(
    *,
    judge: LlmJudge | None,
    case: BenchmarkCase,
    probe: Probe,
    answer: str,
    retrieved_contexts: list[str],
) -> JudgeResult | None:
    if judge is None:
        return None
    return judge.evaluate_answer(
        case_id=case.case_id,
        probe=probe,
        gold_memories=_gold_memories(case, probe.gold_evidence_ids),
        old_memories=_gold_memories(case, probe.old_evidence_ids),
        retrieved_context=retrieved_contexts,
        answer=answer,
    )

def _evaluate_write(
    *,
    judge: LlmJudge | None,
    case_id: str,
    expected_memories: list[GoldMemory],
    noise_memories: list[GoldMemory],
    written_contexts: list[str],
    allowed_other_memories: list[GoldMemory] | None = None,
) -> JudgeResult | None:
    if judge is None:
        return None
    return judge.evaluate_write(
        case_id=case_id,
        expected_memories=expected_memories,
        noise_memories=noise_memories,
        written_context=written_contexts,
        allowed_other_memories=allowed_other_memories,
    )

def _memwing_write_scored_contexts(details: MemorySearchDetails) -> list[str]:
    contexts: list[str] = []
    for result in details.results:
        source = result.get("source")
        if isinstance(source, str) and source in MEMWING_WRITE_RAW_SOURCES:
            continue
        text = _memory_search_result_text(result)
        if text:
            contexts.append(text)
    if contexts or details.results:
        return unique_preserve_order(contexts)
    return details.contexts

def _memory_search_result_text(result: dict[str, Any]) -> str:
    for key in ("text", "snippet"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _gold_memories(case: BenchmarkCase, memory_ids: list[str]) -> list[GoldMemory]:
    by_id = {
        message.id: GoldMemory(id=message.id, time=message.time, fact=message.content)
        for message in case.seed_messages
    }
    for item in case.expected_memory_items:
        by_id.setdefault(item.id, GoldMemory(id=item.id, time=None, fact=item.fact))
    return [by_id[memory_id] for memory_id in memory_ids if memory_id in by_id]

def _expected_memories(case: BenchmarkCase) -> list[GoldMemory]:
    return [
        GoldMemory(id=item.id, time=None, fact=item.fact) for item in case.expected_memory_items
    ]

def _expected_memories_for_other_cases(
    cases: list[BenchmarkCase], current_case_id: str
) -> list[GoldMemory]:
    return [
        GoldMemory(id=item.id, time=None, fact=item.fact)
        for case in cases
        if case.case_id != current_case_id
        for item in case.expected_memory_items
    ]

def _noise_memories(case: BenchmarkCase) -> list[GoldMemory]:
    return [
        GoldMemory(id=message.id, time=message.time, fact=message.content)
        for message in case.seed_messages
        if not message.should_write_memory
    ]

def _safe_memory_search(
    adapter: Any,
    question: str,
    *,
    max_results: int = 5,
    scope: MemWingCaseScope | None = None,
) -> MemorySearchOutcome:
    try:
        if scope is None:
            return MemorySearchOutcome(
                details=adapter.memory_search_details(question, max_results=max_results)
            )
        return MemorySearchOutcome(
            details=adapter.memory_search_details(question, max_results=max_results, scope=scope)
        )
    except Exception as exc:
        return MemorySearchOutcome(
            details=MemorySearchDetails(contexts=[], results=[], latency_ms=0, raw=None),
            error=str(exc),
        )

def _memory_search_raw(search: MemorySearchOutcome) -> dict[str, Any]:
    top = search.details.results[0] if search.details.results else {}
    raw_warnings = search.details.raw.get("warnings") if search.details.raw else None
    raw_diagnostics = search.details.raw.get("diagnostics") if search.details.raw else None
    branch_timings = _current_truth_branch_timings(raw_diagnostics)
    return {
        "memory_search_error": search.error,
        "memory_search_latency_ms": search.details.latency_ms,
        "memory_search_result_count": len(search.details.results),
        "memory_search_results": search.details.results,
        "memory_search_raw": search.details.raw,
        "memory_search_source_mix": _source_mix(search.details.results),
        "memory_search_warnings": raw_warnings if isinstance(raw_warnings, list) else [],
        "memory_search_diagnostics": raw_diagnostics if isinstance(raw_diagnostics, dict) else {},
        "memory_search_branch_timings": branch_timings,
        "memory_search_top_score": top.get("score") if isinstance(top, dict) else None,
        "memory_search_top_vector_score": top.get("vectorScore") if isinstance(top, dict) else None,
        "memory_search_top_text_score": top.get("textScore") if isinstance(top, dict) else None,
        "memory_search_top_path": top.get("path") if isinstance(top, dict) else None,
        "memory_search_top_start_line": top.get("startLine") if isinstance(top, dict) else None,
        "memory_search_top_end_line": top.get("endLine") if isinstance(top, dict) else None,
    }

def _source_mix(results: list[dict[str, Any]]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for result in results:
        source = result.get("source")
        if not isinstance(source, str) or not source:
            source = "unknown"
        mix[source] = mix.get(source, 0) + 1
    return mix
