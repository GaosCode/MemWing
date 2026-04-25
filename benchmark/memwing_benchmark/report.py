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
        "avg_answer_latency_ms": _avg(
            [result.latency_ms for result in results if result.latency_ms is not None]
        ),
        "missing_data": collect_missing_data(results),
    }
    return scores


def collect_missing_data(results: list[NormalizedResult]) -> list[str]:
    missing: list[str] = []
    if any(not result.tokens.available for result in results):
        reasons = {
            result.tokens.missing_reason or "token usage unavailable"
            for result in results
            if not result.tokens.available
        }
        missing.extend(sorted(reasons))
    if any(result.actual_tool_recall_at_1 is None for result in results):
        missing.append("OpenClaw trajectory not found")
    if any(result.latency_ms is None for result in results):
        missing.append("answer latency unavailable")
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
        f"- evidence_correct_rate: {_fmt(scores.get('evidence_correct_rate'))}",
        f"- avg_answer_latency_ms: {_fmt(scores.get('avg_answer_latency_ms'))}",
        "",
        "## Per Case Results",
        "",
        "| case_id | probe_id | score | correct | evidence | recall@5 |",
        "|---|---|---:|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result.case_id} | {result.probe_id} | {result.answer_score} | "
            f"{result.answer_correct} | {result.evidence_correct} | {result.retrieval_recall_at_5} |"
        )
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
    lines.extend(["", "## Notes", "", "- v1 openclaw-native benchmark harness output."])
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


def _avg(values: list[int]) -> float | None:
    if not values:
        return None
    return mean(values)


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
