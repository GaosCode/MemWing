from memwing_benchmark.report import build_scores, render_report
from memwing_benchmark.schema import NormalizedResult, TokenUsage


def test_scores_and_report_include_missing_data() -> None:
    result = NormalizedResult(
        run_id="run1",
        backend="openclaw-native",
        case_id="bs001",
        probe_id="bs001_p1",
        chat_id="oc_xxx",
        seed_chat_id="oc_seed",
        probe_chat_id="oc_probe",
        seed_message_ids=["bs001_s1"],
        probe_message_id=None,
        reply_message_id=None,
        question="负责人是谁？",
        answer="负责人是沈南。",
        expected_answer="负责人是沈南。",
        gold_evidence_ids=["bs001_s1"],
        retrieved_evidence_ids=[],
        retrieved_contexts=["项目晨会结论：云帆看板改造项目负责人确定为沈南。"],
        retrieval_result_count=1,
        retrieval_top_score=0.57,
        retrieval_top_vector_score=0.82,
        retrieval_top_text_score=0.0,
        retrieval_top_path="memory/2026-04-26.md",
        retrieval_top_start_line=1,
        retrieval_top_end_line=5,
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
        durable_memory_available=False,
        extraction_timeout=True,
        memory_search_latency_ms=123,
        latency_ms=None,
        tokens=TokenUsage(available=False, missing_reason="provider did not expose usage"),
        raw={
            "memory_search_results": [
                {
                    "rank": 1,
                    "path": "memory/2026-04-26.md",
                    "startLine": 1,
                    "endLine": 5,
                    "score": 0.57,
                    "vectorScore": 0.82,
                    "textScore": 0.0,
                }
            ]
        },
    )

    scores = build_scores([result])
    report = render_report(
        run_config={"run_id": "run1", "backend": "openclaw-native"}, scores=scores, results=[result]
    )

    assert scores["probe_count"] == 1
    assert scores["answer_accuracy"] == 1.0
    assert scores["avg_memory_search_latency_ms"] == 123
    assert scores["avg_retrieval_top_score"] == 0.57
    assert "provider did not expose usage" in report
    assert "OpenClaw trajectory not found" in report
    assert "durable memory extraction timed out" in report
    assert "avg_memory_search_latency_ms" in report
    assert "memory/2026-04-26.md:1-5" in report
    assert "| bs001 | bs001_p1 | oc_seed | oc_probe | False | True | null |" in report
    assert "OpenClaw Retrieved Contexts" in report
    assert "云帆看板改造项目负责人确定为沈南" in report


def test_write_report_explains_unavailable_file_diff_metrics() -> None:
    result = NormalizedResult(
        run_id="run1",
        backend="memwing",
        case_id="bs001",
        probe_id="bs001_write",
        chat_id=None,
        question="memory_write",
        answer="",
        expected_answer="负责人是沈南。",
        gold_evidence_ids=["bs001_m1"],
        written_contexts=["MemWing memory: 负责人是沈南。"],
        durable_memory_available=True,
        write_expected_count=1,
        write_matched_expected_count=1,
        write_missing_expected_count=0,
        write_changed_file_count=None,
        write_written_claim_count=1,
        write_recall=1.0,
        write_precision=1.0,
        raw={
            "mode": "memory_write",
            "changed_file_metrics_available": False,
            "changed_file_metrics_missing_reason": (
                "MemWing backend is evaluated through HTTP search APIs, not local memory files."
            ),
        },
    )

    report = render_report(
        run_config={"run_id": "run1", "backend": "memwing"},
        scores=build_scores([result]),
        results=[result],
    )

    assert "Write File Metrics Unavailable" in report
    assert "HTTP search APIs" in report
    assert "| bs001 | 1 | 1 | 0 | 1.0000 | 1.0000 | null | 1 |" in report
