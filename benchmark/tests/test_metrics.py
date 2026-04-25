from memwing_benchmark.metrics.retrieval import evidence_correct, recall_at_k


def test_recall_at_k_respects_all_match() -> None:
    gold = ["LT-005", "LT-006"]
    retrieved = ["LT-005", "LT-001", "LT-006"]

    assert recall_at_k(gold, retrieved, 1, match="all") is False
    assert recall_at_k(gold, retrieved, 3, match="all") is True
    assert recall_at_k(gold, retrieved, 1, match="any") is True


def test_evidence_correct_uses_match_policy() -> None:
    assert evidence_correct(["a", "b"], ["a"], match="all") is False
    assert evidence_correct(["a", "b"], ["a"], match="any") is True
    assert evidence_correct([], ["a"], match="all") is None
