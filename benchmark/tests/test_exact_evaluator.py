from memwing_benchmark.evaluators.exact import evaluate_exact
from memwing_benchmark.schema import Probe


def test_exact_evaluator_scores_full_match_with_aliases() -> None:
    probe = Probe(
        id="p1",
        question="负责人是谁？",
        gold_answer="负责人是沈南。",
        must_include=["沈南"],
        must_include_aliases={"沈南": ["由沈南负责"]},
        must_not_include=["周明"],
        gold_evidence_ids=["s1"],
    )

    result = evaluate_exact(probe, "这个项目由沈南负责。", ["s1"])

    assert result.answer_score == 2
    assert result.answer_correct is True
    assert result.evidence_correct is True


def test_exact_evaluator_rejects_forbidden_fact() -> None:
    probe = Probe(
        id="p1",
        question="负责人是谁？",
        gold_answer="负责人是沈南。",
        must_include=["沈南"],
        must_not_include=["周明"],
        gold_evidence_ids=["s1"],
    )

    result = evaluate_exact(probe, "负责人是沈南，周明也负责。", ["s1"])

    assert result.answer_score == 0
    assert result.answer_correct is False
    assert result.reason
