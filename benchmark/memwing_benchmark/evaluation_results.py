from __future__ import annotations

from typing import Any

from memwing_benchmark.evaluators.llm_judge import JudgeResult
from memwing_benchmark.metrics.retrieval import recall_at_k
from memwing_benchmark.run_records import (
    _dict_list,
    _int_dict,
    _latency_ms,
    _nested_str,
    _optional_float,
    _optional_int,
)
from memwing_benchmark.schema import BenchmarkCase, NormalizedResult, Observability, TokenUsage


MEMWING_CHANGED_FILE_METRICS_MISSING_REASON = (
    "MemWing backend is evaluated through HTTP search APIs, not local memory files."
)


def _result_from_eval(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    probe,
    chat_id: str | None,
    seed_message_ids: list[str],
    answer: str,
    retrieved_contexts: list[str],
    retrieved_evidence_ids: list[str],
    actual_tool_evidence_ids: list[str],
    latency_ms: int | None,
    tokens: TokenUsage,
    memory_recall_latency_ms: int | None,
    retrieval_result: JudgeResult | None,
    answer_result: JudgeResult | None,
    raw: dict[str, Any],
) -> NormalizedResult:
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=probe.id,
        chat_id=chat_id,
        seed_chat_id=raw.get("seed_chat_id") if isinstance(raw.get("seed_chat_id"), str) else None,
        probe_chat_id=raw.get("probe_chat_id")
        if isinstance(raw.get("probe_chat_id"), str)
        else None,
        seed_message_ids=seed_message_ids,
        probe_message_id=_nested_str(raw, "probe_send_result", "message_id"),
        reply_message_id=_nested_str(raw, "reply", "message_id"),
        question=probe.question,
        answer=answer,
        expected_answer=probe.gold_answer,
        gold_evidence_ids=probe.gold_evidence_ids,
        retrieved_evidence_ids=retrieved_evidence_ids,
        retrieved_contexts=retrieved_contexts,
        retrieval_result_count=_optional_int(raw.get("memory_search_result_count")),
        retrieval_top_score=_optional_float(raw.get("memory_search_top_score")),
        retrieval_top_vector_score=_optional_float(raw.get("memory_search_top_vector_score")),
        retrieval_top_text_score=_optional_float(raw.get("memory_search_top_text_score")),
        retrieval_top_path=(
            raw.get("memory_search_top_path")
            if isinstance(raw.get("memory_search_top_path"), str)
            else None
        ),
        retrieval_top_start_line=_optional_int(raw.get("memory_search_top_start_line")),
        retrieval_top_end_line=_optional_int(raw.get("memory_search_top_end_line")),
        retrieval_source_mix=_int_dict(raw.get("memory_search_source_mix")),
        memory_search_warnings=_dict_list(raw.get("memory_search_warnings")),
        readiness_summary=raw.get("readiness") if isinstance(raw.get("readiness"), dict) else {},
        retrieval_recall_at_1=(
            retrieval_result.retrieval.recall_at_1 if retrieval_result else None
        ),
        retrieval_recall_at_3=(
            retrieval_result.retrieval.recall_at_3 if retrieval_result else None
        ),
        retrieval_recall_at_5=(
            retrieval_result.retrieval.recall_at_5 if retrieval_result else None
        ),
        actual_tool_recall_at_1=recall_at_k(
            probe.gold_evidence_ids, actual_tool_evidence_ids, 1, match=probe.evidence_match
        )
        if actual_tool_evidence_ids
        else None,
        actual_tool_recall_at_3=recall_at_k(
            probe.gold_evidence_ids, actual_tool_evidence_ids, 3, match=probe.evidence_match
        )
        if actual_tool_evidence_ids
        else None,
        actual_tool_recall_at_5=recall_at_k(
            probe.gold_evidence_ids, actual_tool_evidence_ids, 5, match=probe.evidence_match
        )
        if actual_tool_evidence_ids
        else None,
        answer_score=answer_result.answer.answer_score if answer_result else None,
        answer_correct=answer_result.answer.answer_correct if answer_result else None,
        temporal_correct=answer_result.answer.temporal_correct if answer_result else None,
        evidence_correct=answer_result.answer.evidence_correct if answer_result else None,
        noise_polluted=answer_result.answer.noise_polluted if answer_result else None,
        seed_completed_at=raw.get("seed_completed_at")
        if isinstance(raw.get("seed_completed_at"), str)
        else None,
        first_memory_available_at=(
            raw.get("first_memory_available_at")
            if isinstance(raw.get("first_memory_available_at"), str)
            else None
        ),
        durable_memory_available=(
            raw.get("durable_memory_available")
            if isinstance(raw.get("durable_memory_available"), bool)
            else None
        ),
        extraction_timeout=(
            raw.get("extraction_timeout")
            if isinstance(raw.get("extraction_timeout"), bool)
            else False
        ),
        probe_sent_at=raw.get("probe_sent_at")
        if isinstance(raw.get("probe_sent_at"), str)
        else None,
        answer_received_at=(
            raw.get("answer_received_at")
            if isinstance(raw.get("answer_received_at"), str)
            else None
        ),
        memory_search_latency_ms=_optional_int(raw.get("memory_search_latency_ms")),
        memory_availability_latency_ms=_latency_ms(
            raw.get("seed_completed_at"), raw.get("first_memory_available_at")
        )
        if isinstance(raw.get("seed_completed_at"), str)
        and isinstance(raw.get("first_memory_available_at"), str)
        else None,
        latency_ms=latency_ms,
        tokens=tokens,
        observability=Observability(
            memory_write_latency_ms=None,
            memory_availability_latency_ms=_latency_ms(
                raw.get("seed_completed_at"), raw.get("first_memory_available_at")
            )
            if isinstance(raw.get("seed_completed_at"), str)
            and isinstance(raw.get("first_memory_available_at"), str)
            else None,
            memory_write_tokens=None,
            memory_recall_latency_ms=memory_recall_latency_ms
            if memory_recall_latency_ms is not None
            else _optional_int(raw.get("memory_search_latency_ms")),
            memory_recall_tokens=None,
            answer_latency_ms=latency_ms,
            notes=[
                "OpenClaw native does not expose stable memory write latency/token usage.",
            ],
        ),
        raw={
            **raw,
            "retrieval_judge": retrieval_result.model_dump(mode="json")
            if retrieval_result
            else None,
            "answer_judge": answer_result.model_dump(mode="json") if answer_result else None,
        },
    )

def _result_from_write(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    chat_id: str | None,
    seed_message_ids: list[str],
    written_contexts: list[str],
    changed_files: list[dict[str, Any]],
    seed_completed_at: str | None,
    first_changed_at: str | None,
    timeout: bool,
    write_result: JudgeResult | None,
    phase: str = "full",
) -> NormalizedResult:
    expected_count = len(case.expected_memory_items)
    write = write_result.write if write_result else None
    matched_count = len(write.matched_expected_memory_ids) if write else None
    missing_count = (
        len(write.missing_expected_memory_ids)
        if write and write.missing_expected_memory_ids
        else (expected_count - matched_count if matched_count is not None else None)
    )
    unexpected_count = len(write.unexpected_facts) if write else None
    noise_count = len(write.noise_facts) if write else None
    wrong_count = len(write.wrong_facts) if write else None
    stale_count = len(write.stale_facts) if write else None
    write_ratios = _write_quality_ratios(write_result)
    memory_write_latency_ms = (
        _latency_ms(seed_completed_at, first_changed_at)
        if seed_completed_at and first_changed_at
        else None
    )
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=f"{case.case_id}_write",
        chat_id=chat_id,
        seed_chat_id=chat_id,
        seed_message_ids=seed_message_ids,
        question="memory_write",
        answer="",
        expected_answer="\n".join(item.fact for item in case.expected_memory_items),
        gold_evidence_ids=[item.id for item in case.expected_memory_items],
        retrieved_contexts=[],
        written_contexts=written_contexts,
        durable_memory_available=bool(changed_files),
        extraction_timeout=timeout,
        seed_completed_at=seed_completed_at,
        first_memory_available_at=first_changed_at,
        memory_write_latency_ms=memory_write_latency_ms,
        memory_availability_latency_ms=memory_write_latency_ms,
        write_expected_count=expected_count,
        write_matched_expected_count=matched_count,
        write_missing_expected_count=missing_count,
        write_unexpected_count=unexpected_count,
        write_noise_count=noise_count,
        write_wrong_count=wrong_count,
        write_stale_count=stale_count,
        write_scored_context_count=len(written_contexts),
        write_changed_file_count=len(changed_files),
        write_written_claim_count=write.written_claim_count if write else None,
        write_recall=write.write_recall if write else None,
        write_precision=write.write_precision if write else None,
        write_target_precision=write_ratios["target_precision"],
        write_expected_memory_ratio=write_ratios["target_precision"],
        write_non_target_ratio=write_ratios["non_target_ratio"],
        write_forbidden_memory_ratio=write_ratios["forbidden_memory_ratio"],
        tokens=TokenUsage(available=False, missing_reason="write mode does not collect tokens"),
        observability=Observability(
            memory_write_latency_ms=memory_write_latency_ms,
            memory_availability_latency_ms=memory_write_latency_ms,
            notes=[_write_observability_note(phase)],
        ),
        raw={
            "mode": "memory_write",
            "phase": phase,
            "seed_completed_at": seed_completed_at,
            "first_memory_available_at": first_changed_at,
            "durable_memory_available": bool(changed_files),
            "extraction_timeout": timeout,
            "changed_memory_files": changed_files,
            "write_judge": write_result.model_dump(mode="json") if write_result else None,
            "write_quality_ratios": write_ratios,
        },
    )

def _result_from_write_ingest(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    chat_id: str | None,
    seed_message_ids: list[str],
    seed_completed_at: str | None,
    raw_extra: dict[str, Any] | None = None,
    observability_note: str | None = None,
) -> NormalizedResult:
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=f"{case.case_id}_write_ingest",
        chat_id=chat_id,
        seed_chat_id=chat_id,
        probe_chat_id=chat_id,
        seed_message_ids=seed_message_ids,
        question="memory_write_ingest",
        answer="",
        expected_answer="\n".join(item.fact for item in case.expected_memory_items),
        gold_evidence_ids=[item.id for item in case.expected_memory_items],
        durable_memory_available=None,
        extraction_timeout=False,
        seed_completed_at=seed_completed_at,
        tokens=TokenUsage(available=False, missing_reason="write ingest does not collect tokens"),
        observability=Observability(
            notes=[
                observability_note
                or "Write ingest phase only sends seed messages; evaluate memory after OpenClaw finishes writing.",
            ],
        ),
        raw={
            "mode": "memory_write_ingest",
            "phase": "ingest",
            "seed_completed_at": seed_completed_at,
            **(raw_extra or {}),
        },
    )

def _result_from_memwing_write(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    seed_message_ids: list[str],
    written_contexts: list[str],
    search_latencies: list[int],
    search_errors: list[str],
    write_result: JudgeResult | None,
    searches: list[dict[str, Any]],
    readiness_summary: dict[str, Any] | None = None,
    scored_context_count: int | None = None,
) -> NormalizedResult:
    expected_count = len(case.expected_memory_items)
    write = write_result.write if write_result else None
    matched_count = len(write.matched_expected_memory_ids) if write else None
    missing_count = (
        len(write.missing_expected_memory_ids)
        if write and write.missing_expected_memory_ids
        else (expected_count - matched_count if matched_count is not None else None)
    )
    unexpected_count = len(write.unexpected_facts) if write else None
    noise_count = len(write.noise_facts) if write else None
    wrong_count = len(write.wrong_facts) if write else None
    stale_count = len(write.stale_facts) if write else None
    write_ratios = _write_quality_ratios(write_result)
    memory_recall_latency_ms = sum(search_latencies) if search_latencies else None
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=f"{case.case_id}_write",
        chat_id=None,
        seed_message_ids=seed_message_ids,
        question="memory_write",
        answer="",
        expected_answer="\n".join(item.fact for item in case.expected_memory_items),
        gold_evidence_ids=[item.id for item in case.expected_memory_items],
        written_contexts=written_contexts,
        durable_memory_available=bool(written_contexts),
        extraction_timeout=False,
        memory_search_latency_ms=memory_recall_latency_ms,
        write_expected_count=expected_count,
        write_matched_expected_count=matched_count,
        write_missing_expected_count=missing_count,
        write_unexpected_count=unexpected_count,
        write_noise_count=noise_count,
        write_wrong_count=wrong_count,
        write_stale_count=stale_count,
        write_scored_context_count=scored_context_count,
        write_changed_file_count=None,
        write_written_claim_count=write.written_claim_count if write else None,
        write_recall=write.write_recall if write else None,
        write_precision=write.write_precision if write else None,
        write_target_precision=write_ratios["target_precision"],
        write_expected_memory_ratio=write_ratios["target_precision"],
        write_non_target_ratio=write_ratios["non_target_ratio"],
        write_forbidden_memory_ratio=write_ratios["forbidden_memory_ratio"],
        tokens=TokenUsage(available=False, missing_reason="write mode does not collect tokens"),
        observability=Observability(
            memory_recall_latency_ms=memory_recall_latency_ms,
            notes=[
                "MemWing write evaluate scores durable memory through HTTP search APIs.",
                MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
            ],
        ),
        readiness_summary=readiness_summary or {},
        raw={
            "mode": "memory_write",
            "phase": "evaluate",
            "backend": backend,
            "durable_memory_available": bool(written_contexts),
            "extraction_timeout": False,
            "changed_memory_files": None,
            "changed_file_metrics_available": False,
            "changed_file_metrics_missing_reason": MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
            "memory_searches": searches,
            "memory_search_errors": search_errors,
            "readiness": readiness_summary,
            "write_judge": write_result.model_dump(mode="json") if write_result else None,
            "write_quality_ratios": write_ratios,
        },
    )

def _write_observability_note(phase: str) -> str:
    if phase == "evaluate":
        return "Write evaluate phase scores current durable memory files without sending Feishu messages."
    return "Write mode evaluates durable memory file diffs without forced flush."

def _write_quality_ratios(write_result: JudgeResult | None) -> dict[str, float | None]:
    if write_result is None:
        return {
            "target_precision": None,
            "non_target_ratio": None,
            "forbidden_memory_ratio": None,
        }
    write = write_result.write
    expected_count = len(write.matched_expected_memory_ids)
    non_target_count = len(write.unexpected_facts)
    forbidden_count = len(write.noise_facts)
    classified_count = (
        expected_count
        + non_target_count
        + forbidden_count
        + len(write.wrong_facts)
        + len(write.stale_facts)
    )
    if classified_count <= 0:
        return {
            "target_precision": 0.0,
            "non_target_ratio": 0.0,
            "forbidden_memory_ratio": 0.0,
        }
    return {
        "target_precision": expected_count / classified_count,
        "non_target_ratio": non_target_count / classified_count,
        "forbidden_memory_ratio": forbidden_count / classified_count,
    }
