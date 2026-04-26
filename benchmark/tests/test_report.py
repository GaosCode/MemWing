from memwing_benchmark.report import build_scores, render_report
from memwing_benchmark.schema import NormalizedResult, TokenUsage


def test_scores_and_report_include_missing_data() -> None:
    result = NormalizedResult(
        run_id="run1",
        backend="openclaw-native",
        case_id="bs001",
        probe_id="bs001_p1",
        chat_id="oc_xxx",
        seed_message_ids=["bs001_s1"],
        probe_message_id=None,
        reply_message_id=None,
        question="负责人是谁？",
        answer="负责人是沈南。",
        expected_answer="负责人是沈南。",
        gold_evidence_ids=["bs001_s1"],
        retrieved_evidence_ids=[],
        retrieved_contexts=["项目晨会结论：云帆看板改造项目负责人确定为沈南。"],
        retrieval_recall_at_1=False,
        retrieval_recall_at_3=False,
        retrieval_recall_at_5=False,
        actual_tool_recall_at_1=None,
        actual_tool_recall_at_3=None,
        actual_tool_recall_at_5=None,
        answer_score=2,
        answer_correct=True,
        temporal_correct=None,
        evidence_correct=False,
        noise_polluted=False,
        latency_ms=None,
        tokens=TokenUsage(available=False, missing_reason="provider did not expose usage"),
    )

    scores = build_scores([result])
    report = render_report(
        run_config={"run_id": "run1", "backend": "openclaw-native"}, scores=scores, results=[result]
    )

    assert scores["probe_count"] == 1
    assert scores["answer_accuracy"] == 1.0
    assert "provider did not expose usage" in report
    assert "OpenClaw trajectory not found" in report
    assert "OpenClaw Retrieved Contexts" in report
    assert "云帆看板改造项目负责人确定为沈南" in report
