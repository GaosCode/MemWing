from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any

from memwing_benchmark.json_utils import dumps_json, dumps_jsonl_row
from memwing_benchmark.schema import NormalizedResult


def build_scores(results: list[NormalizedResult]) -> dict[str, Any]:
    probe_count = len(results)
    answer_scores = [result.answer_score for result in results if result.answer_score is not None]
    answer_correct = [
        result.answer_correct for result in results if result.answer_correct is not None
    ]
    evidence_values = [
        result.evidence_correct for result in results if result.evidence_correct is not None
    ]

    scores: dict[str, Any] = {
        "probe_count": probe_count,
        "answer_accuracy": _rate(answer_correct),
        "avg_answer_score": mean(answer_scores) if answer_scores else None,
        "evidence_correct_rate": _rate(evidence_values),
        "retrieval_recall_at_1": _rate(
            [
                result.retrieval_recall_at_1
                for result in results
                if result.retrieval_recall_at_1 is not None
            ]
        ),
        "retrieval_recall_at_3": _rate(
            [
                result.retrieval_recall_at_3
                for result in results
                if result.retrieval_recall_at_3 is not None
            ]
        ),
        "retrieval_recall_at_5": _rate(
            [
                result.retrieval_recall_at_5
                for result in results
                if result.retrieval_recall_at_5 is not None
            ]
        ),
        "retrieval_empty_rate": _rate(
            [
                result.retrieval_result_count == 0
                for result in results
                if result.retrieval_result_count is not None
            ]
        ),
        "avg_retrieval_result_count": _avg(
            [
                result.retrieval_result_count
                for result in results
                if result.retrieval_result_count is not None
            ]
        ),
        "avg_retrieval_top_score": _avg(
            [
                result.retrieval_top_score
                for result in results
                if result.retrieval_top_score is not None
            ]
        ),
        "avg_retrieval_top_vector_score": _avg(
            [
                result.retrieval_top_vector_score
                for result in results
                if result.retrieval_top_vector_score is not None
            ]
        ),
        "avg_retrieval_top_text_score": _avg(
            [
                result.retrieval_top_text_score
                for result in results
                if result.retrieval_top_text_score is not None
            ]
        ),
        "avg_memory_search_latency_ms": _avg(
            [
                result.memory_search_latency_ms
                for result in results
                if result.memory_search_latency_ms is not None
            ]
        ),
        "write_recall": _avg(
            [result.write_recall for result in results if result.write_recall is not None]
        ),
        "write_precision": _avg(
            [result.write_precision for result in results if result.write_precision is not None]
        ),
        "write_target_precision": _avg(
            [
                result.write_target_precision
                for result in results
                if result.write_target_precision is not None
            ]
        ),
        "write_expected_memory_ratio": _avg(
            [
                result.write_expected_memory_ratio
                for result in results
                if result.write_expected_memory_ratio is not None
            ]
        ),
        "write_non_target_ratio": _avg(
            [
                result.write_non_target_ratio
                for result in results
                if result.write_non_target_ratio is not None
            ]
        ),
        "write_forbidden_memory_ratio": _avg(
            [
                result.write_forbidden_memory_ratio
                for result in results
                if result.write_forbidden_memory_ratio is not None
            ]
        ),
        "avg_write_scored_context_count": _avg(
            [
                result.write_scored_context_count
                for result in results
                if result.write_scored_context_count is not None
            ]
        ),
        "avg_write_changed_file_count": _avg(
            [
                result.write_changed_file_count
                for result in results
                if result.write_changed_file_count is not None
            ]
        ),
        "avg_write_written_claim_count": _avg(
            [
                result.write_written_claim_count
                for result in results
                if result.write_written_claim_count is not None
            ]
        ),
        "avg_memory_write_latency_ms": _avg(
            [
                result.memory_write_latency_ms
                for result in results
                if result.memory_write_latency_ms is not None
            ]
        ),
        "avg_answer_latency_ms": _avg(
            [result.latency_ms for result in results if result.latency_ms is not None]
        ),
        "missing_data": collect_missing_data(results),
    }
    return scores


def collect_missing_data(results: list[NormalizedResult]) -> list[str]:
    missing: list[str] = []
    scored_results = [
        result for result in results if result.raw.get("mode") != "memory_write_ingest"
    ]
    if not scored_results:
        return []
    if any(not result.tokens.available for result in scored_results):
        reasons = {
            result.tokens.missing_reason or "token usage unavailable"
            for result in scored_results
            if not result.tokens.available
        }
        missing.extend(sorted(reasons))
    if any(result.actual_tool_recall_at_1 is None for result in scored_results):
        missing.append("OpenClaw trajectory not found")
    if any(result.latency_ms is None for result in scored_results):
        missing.append("answer latency unavailable")
    if any(result.retrieval_recall_at_5 is None for result in scored_results):
        missing.append("retrieval judge unavailable")
    if any(
        result.raw.get("mode") != "memory_write" and result.memory_search_latency_ms is None
        for result in scored_results
    ):
        missing.append("memory search latency unavailable")
    if any(
        result.raw.get("mode") == "memory_write" and result.write_recall is None
        for result in scored_results
    ):
        missing.append("write judge unavailable")
    if any(result.answer and result.answer_score is None for result in scored_results):
        missing.append("answer judge unavailable")
    if any(result.raw.get("memory_search_error") for result in scored_results):
        missing.append("OpenClaw memory search failed")
    if any(result.extraction_timeout for result in scored_results):
        missing.append("durable memory extraction timed out")
    return sorted(set(missing))


def render_report(
    *,
    run_config: dict[str, Any],
    scores: dict[str, Any],
    results: list[NormalizedResult],
) -> str:
    lines = [
        "# Benchmark Report",
        "",
        "## Run Config",
        "",
        f"- run_id: `{run_config.get('run_id', '')}`",
        f"- backend: `{run_config.get('backend', '')}`",
        f"- case_file: `{run_config.get('case_file', '')}`",
        "",
        "## Summary",
        "",
        f"- probes: {scores.get('probe_count', 0)}",
        f"- answer_accuracy: {_fmt(scores.get('answer_accuracy'))}",
        f"- avg_answer_score: {_fmt(scores.get('avg_answer_score'))}",
        "",
        "## Metrics",
        "",
        f"- retrieval_recall_at_1: {_fmt(scores.get('retrieval_recall_at_1'))}",
        f"- retrieval_recall_at_3: {_fmt(scores.get('retrieval_recall_at_3'))}",
        f"- retrieval_recall_at_5: {_fmt(scores.get('retrieval_recall_at_5'))}",
        f"- retrieval_empty_rate: {_fmt(scores.get('retrieval_empty_rate'))}",
        f"- avg_retrieval_result_count: {_fmt(scores.get('avg_retrieval_result_count'))}",
        f"- avg_retrieval_top_score: {_fmt(scores.get('avg_retrieval_top_score'))}",
        f"- avg_retrieval_top_vector_score: {_fmt(scores.get('avg_retrieval_top_vector_score'))}",
        f"- avg_retrieval_top_text_score: {_fmt(scores.get('avg_retrieval_top_text_score'))}",
        f"- avg_memory_search_latency_ms: {_fmt(scores.get('avg_memory_search_latency_ms'))}",
        f"- write_recall: {_fmt(scores.get('write_recall'))}",
        f"- write_precision: {_fmt(scores.get('write_precision'))}",
        f"- write_target_precision: {_fmt(scores.get('write_target_precision'))}",
        f"- write_expected_memory_ratio: {_fmt(scores.get('write_expected_memory_ratio'))}",
        f"- write_non_target_ratio: {_fmt(scores.get('write_non_target_ratio'))}",
        f"- write_forbidden_memory_ratio: {_fmt(scores.get('write_forbidden_memory_ratio'))}",
        f"- avg_write_scored_context_count: {_fmt(scores.get('avg_write_scored_context_count'))}",
        f"- avg_write_changed_file_count: {_fmt(scores.get('avg_write_changed_file_count'))}",
        f"- avg_write_written_claim_count: {_fmt(scores.get('avg_write_written_claim_count'))}",
        f"- avg_memory_write_latency_ms: {_fmt(scores.get('avg_memory_write_latency_ms'))}",
        f"- evidence_correct_rate: {_fmt(scores.get('evidence_correct_rate'))}",
        f"- avg_answer_latency_ms: {_fmt(scores.get('avg_answer_latency_ms'))}",
        "",
        "## MemWing Pipeline",
        "",
        "| case_id | probe_id | ready | sources | warnings | pending_jobs | dead_letters |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for result in results:
        lines.append(
            f"| {result.case_id} | {result.probe_id} | {_fmt(_readiness_ready(result))} | "
            f"{_fmt(_readiness_sources_text(result))} | "
            f"{_fmt(_pipeline_warnings_text(result))} | "
            f"{_fmt(_readiness_job_count(result, 'pending_count'))} | "
            f"{_fmt(_readiness_job_count(result, 'dead_letter_count'))} |"
        )
    lines.extend(
        [
            "",
        "## Durable Memory",
        "",
        "| case_id | probe_id | seed_chat_id | probe_chat_id | available | timeout | latency_ms |",
        "|---|---|---|---|---|---|---:|",
        ]
    )
    for result in results:
        lines.append(
            f"| {result.case_id} | {result.probe_id} | {_fmt(result.seed_chat_id)} | "
            f"{_fmt(result.probe_chat_id)} | {result.durable_memory_available} | "
            f"{result.extraction_timeout} | {_fmt(result.memory_availability_latency_ms)} |"
        )
    lines.extend(
        [
            "",
            "## Per Case Results",
            "",
            "| case_id | probe_id | answer_score | correct | evidence | recall@1 | recall@3 | recall@5 | hits | search_ms | top_score | top_vector | top_text | top_path |",
            "|---|---|---:|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for result in results:
        lines.append(
            f"| {result.case_id} | {result.probe_id} | {result.answer_score} | "
            f"{result.answer_correct} | {result.evidence_correct} | "
            f"{result.retrieval_recall_at_1} | {result.retrieval_recall_at_3} | "
            f"{result.retrieval_recall_at_5} | {_fmt(result.retrieval_result_count)} | "
            f"{_fmt(result.memory_search_latency_ms)} | {_fmt(result.retrieval_top_score)} | "
            f"{_fmt(result.retrieval_top_vector_score)} | {_fmt(result.retrieval_top_text_score)} | "
            f"{_fmt(_top_location(result))} |"
        )
    if any(result.raw.get("mode") == "memory_write_ingest" for result in results):
        lines.extend(
            [
                "",
                "## Write Ingest",
                "",
                "| case_id | chat_id | sent_seed_messages | completed_at |",
                "|---|---|---:|---|",
            ]
        )
        for result in results:
            if result.raw.get("mode") != "memory_write_ingest":
                continue
            lines.append(
                f"| {result.case_id} | {_fmt(result.seed_chat_id)} | "
                f"{len(result.seed_message_ids)} | {_fmt(result.seed_completed_at)} |"
            )
    if any(result.raw.get("mode") == "memory_write" for result in results):
        lines.extend(
            [
                "",
                "## Write Results",
                "",
                "| case_id | expected | matched | missing | recall | judge_precision | target_precision | non_target_ratio | forbidden_ratio | scored_contexts | changed_files | claims | noise | wrong | stale | timeout |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for result in results:
            if result.raw.get("mode") != "memory_write":
                continue
            lines.append(
                f"| {result.case_id} | {_fmt(result.write_expected_count)} | "
                f"{_fmt(result.write_matched_expected_count)} | "
                f"{_fmt(result.write_missing_expected_count)} | "
                f"{_fmt(result.write_recall)} | {_fmt(result.write_precision)} | "
                f"{_fmt(result.write_target_precision)} | "
                f"{_fmt(result.write_non_target_ratio)} | "
                f"{_fmt(result.write_forbidden_memory_ratio)} | "
                f"{_fmt(result.write_scored_context_count)} | "
                f"{_fmt(result.write_changed_file_count)} | "
                f"{_fmt(result.write_written_claim_count)} | "
                f"{_fmt(result.write_noise_count)} | {_fmt(result.write_wrong_count)} | "
                f"{_fmt(result.write_stale_count)} | {result.extraction_timeout} |"
            )
        unavailable_file_metrics = [
            result
            for result in results
            if result.raw.get("mode") == "memory_write"
            and result.raw.get("changed_file_metrics_available") is False
        ]
        if unavailable_file_metrics:
            lines.extend(
                [
                    "",
                    "## Write File Metrics Unavailable",
                    "",
                    "| case_id | reason |",
                    "|---|---|",
                ]
            )
            for result in unavailable_file_metrics:
                lines.append(
                    f"| {result.case_id} | "
                    f"{_fmt(result.raw.get('changed_file_metrics_missing_reason'))} |"
                )
        lines.extend(["", "## Written Memory Contexts", ""])
        for result in results:
            if not result.written_contexts:
                continue
            lines.extend(["", f"### {result.case_id}", ""])
            for index, context in enumerate(result.written_contexts, start=1):
                lines.extend(["", f"**Changed block {index}**", "", "````text", context, "````"])
    lines.extend(["", "## OpenClaw Retrieved Contexts", ""])
    if any(result.retrieved_contexts for result in results):
        lines.append(
            "这些片段是 OpenClaw `memory search` 返回给 retrieval judge 的 top context，"
            "用于观察 seed 记忆被索引后实际可检索到的内容。"
        )
        for result in results:
            if not result.retrieved_contexts:
                continue
            lines.extend(["", f"### {result.case_id} / {result.probe_id}", ""])
            for index, context in enumerate(result.retrieved_contexts[:3], start=1):
                hit = _raw_search_hit(result, index)
                meta = _format_hit_meta(hit) if hit else f"rank={index}"
                lines.extend(
                    [
                        f"**Top {index}** `{meta}`",
                        "",
                        "````text",
                        _truncate_context(context),
                        "````",
                        "",
                    ]
                )
    else:
        lines.append("- none")
    lines.extend(["", "## Failures", ""])
    failures = [result for result in results if result.answer_correct is False]
    if failures:
        for failure in failures:
            lines.append(
                f"- `{failure.case_id}/{failure.probe_id}`: {failure.answer[:120] or 'no answer'}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Missing Data", ""])
    missing = scores.get("missing_data") or []
    if missing:
        for item in missing:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- v1 openclaw-native benchmark harness output.",
            "- 本轮 benchmark 不评测实时飞书消息写入长期记忆的延迟与成功率。",
            "- 本轮评测的是历史协作记忆已经沉淀后，OpenClaw native memory 是否能正确检索并用于回答。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_run_outputs(
    *,
    run_dir: Path,
    run_config: dict[str, Any],
    results: list[NormalizedResult],
    raw_records: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw").mkdir(exist_ok=True)
    scores = build_scores(results)
    (run_dir / "config.json").write_text(dumps_json(run_config) + "\n", encoding="utf-8")
    (run_dir / "scores.json").write_text(dumps_json(scores) + "\n", encoding="utf-8")
    rows = [dumps_jsonl_row(result.model_dump(mode="json")) for result in results]
    (run_dir / "normalized.jsonl").write_text(
        "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8"
    )
    (run_dir / "report.md").write_text(
        render_report(run_config=run_config, scores=scores, results=results),
        encoding="utf-8",
    )
    if raw_records is not None:
        (run_dir / "raw" / "records.json").write_text(
            dumps_json(raw_records) + "\n", encoding="utf-8"
        )
    return scores


def _rate(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)


def _avg(values: list[int | float]) -> float | None:
    if not values:
        return None
    return mean(values)


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _truncate_context(value: str, limit: int = 1200) -> str:
    normalized = value.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n...[truncated]"


def _raw_search_hit(result: NormalizedResult, rank: int) -> dict[str, Any] | None:
    hits = result.raw.get("memory_search_results")
    if not isinstance(hits, list):
        return None
    index = rank - 1
    if index < 0 or index >= len(hits):
        return None
    hit = hits[index]
    return hit if isinstance(hit, dict) else None


def _format_hit_meta(hit: dict[str, Any]) -> str:
    parts = [
        f"rank={_fmt(hit.get('rank'))}",
        f"score={_fmt(hit.get('score'))}",
        f"vector={_fmt(hit.get('vectorScore'))}",
        f"text={_fmt(hit.get('textScore'))}",
        f"path={_fmt(_hit_location(hit))}",
    ]
    return " ".join(parts)


def _top_location(result: NormalizedResult) -> str | None:
    if not result.retrieval_top_path:
        return None
    if result.retrieval_top_start_line is None or result.retrieval_top_end_line is None:
        return result.retrieval_top_path
    return f"{result.retrieval_top_path}:{result.retrieval_top_start_line}-{result.retrieval_top_end_line}"


def _hit_location(hit: dict[str, Any]) -> str | None:
    path = hit.get("path")
    if not isinstance(path, str):
        return None
    start = hit.get("startLine")
    end = hit.get("endLine")
    if isinstance(start, int) and isinstance(end, int):
        return f"{path}:{start}-{end}"
    return path


def _source_mix_text(source_mix: dict[str, int]) -> str | None:
    if not source_mix:
        return None
    return ", ".join(f"{key}:{source_mix[key]}" for key in sorted(source_mix))


def _warnings_text(warnings: list[dict[str, Any]]) -> str | None:
    if not warnings:
        return None
    labels: list[str] = []
    for warning in warnings:
        branch = warning.get("branch")
        reason = warning.get("reason_code")
        if isinstance(branch, str) and isinstance(reason, str):
            labels.append(f"{branch}:{reason}")
    return ", ".join(labels) if labels else f"{len(warnings)} warning(s)"


def _readiness_ready(result: NormalizedResult) -> bool | None:
    readiness = _readiness_final(result)
    ready = readiness.get("ready")
    return ready if isinstance(ready, bool) else None


def _readiness_job_count(result: NormalizedResult, field_name: str) -> int | None:
    readiness = _readiness_final(result)
    jobs = readiness.get("jobs")
    if isinstance(jobs, dict):
        value = jobs.get(field_name)
        return value if isinstance(value, int) else None
    outbox = readiness.get("outbox")
    if not isinstance(outbox, dict):
        return None
    outbox_field = {
        "pending_count": "pending",
        "dead_letter_count": "dead_letter",
    }.get(field_name, field_name)
    value = outbox.get(outbox_field)
    return value if isinstance(value, int) else None


def _readiness_final(result: NormalizedResult) -> dict[str, Any]:
    final = result.readiness_summary.get("final")
    if isinstance(final, dict):
        return final
    return result.readiness_summary


def _readiness_sources_text(result: NormalizedResult) -> str | None:
    readiness = _readiness_final(result)
    derived = readiness.get("derived")
    if isinstance(derived, dict):
        labels: list[str] = []
        for layer in ("working_memory", "page_memory", "memory_items", "evidence", "graph"):
            item = derived.get(layer)
            if not isinstance(item, dict):
                continue
            ready = item.get("ready")
            count = item.get("count")
            pending = item.get("pending")
            if isinstance(count, int):
                labels.append(f"{layer}:{'ready' if ready is True else 'not_ready'}:{count}")
            elif isinstance(pending, int):
                labels.append(f"{layer}:{'ready' if ready is True else 'not_ready'}:pending={pending}")
        if labels:
            return ", ".join(labels)
    return _source_mix_text(result.retrieval_source_mix)


def _pipeline_warnings_text(result: NormalizedResult) -> str | None:
    readiness = _readiness_final(result)
    warnings = readiness.get("warnings")
    if isinstance(warnings, list) and warnings:
        labels = [warning for warning in warnings if isinstance(warning, str)]
        if labels:
            return ", ".join(labels)
    return _warnings_text(result.memory_search_warnings)
