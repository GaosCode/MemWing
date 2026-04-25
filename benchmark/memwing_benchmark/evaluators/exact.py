from __future__ import annotations

from memwing_benchmark.evaluators.llm_judge import JudgeResult
from memwing_benchmark.metrics.retrieval import evidence_correct
from memwing_benchmark.schema import Probe


def _contains(answer: str, term: str, aliases: list[str]) -> bool:
    candidates = [term, *aliases]
    return any(candidate and candidate in answer for candidate in candidates)


def evaluate_exact(probe: Probe, answer: str, retrieved_evidence_ids: list[str]) -> JudgeResult:
    forbidden = [term for term in probe.must_not_include if term and term in answer]
    hits = [
        term
        for term in probe.must_include
        if _contains(answer, term, probe.must_include_aliases.get(term, []))
    ]
    required_count = len(probe.must_include)

    if forbidden:
        score = 0
        reason = f"包含禁止事实：{', '.join(forbidden[:3])}"
    elif required_count == 0:
        score = 2 if answer.strip() else 0
        reason = "无 must_include，按非空回答判定" if answer.strip() else "未回答"
    elif len(hits) == required_count:
        score = 2
        reason = "命中全部关键字段"
    elif hits:
        score = 1
        reason = "只命中部分关键字段"
    else:
        score = 0
        reason = "未命中关键字段"

    temporal_correct = None
    if probe.temporal_expectation:
        temporal_correct = score == 2

    ev_correct = evidence_correct(
        probe.gold_evidence_ids, retrieved_evidence_ids, match=probe.evidence_match
    )
    return JudgeResult(
        answer_score=score,
        answer_correct=score == 2,
        evidence_correct=ev_correct if ev_correct is not None else False,
        temporal_correct=temporal_correct,
        noise_polluted=False,
        reason=reason,
    )
