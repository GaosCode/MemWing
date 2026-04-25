from pathlib import Path

from memwing_benchmark.collectors.openclaw_trajectory import parse_trajectory_dir


def test_parse_trajectory_extracts_tool_evidence_and_usage(tmp_path: Path) -> None:
    trace = tmp_path / "session.trajectory.jsonl"
    trace.write_text(
        "\n".join(
            [
                '{"type":"tool.completed","tool":"memory_search","result":{"items":[{"text":"[MSG:bs001_s1] 负责人是沈南"}],"debug":{"searchMs":42}}}',
                '{"type":"model.completed","usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15}}',
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_trajectory_dir(tmp_path)

    assert parsed.evidence_ids == ["bs001_s1"]
    assert parsed.memory_recall_latency_ms == 42
    assert parsed.tokens.total == 15
    assert parsed.paths == [trace]
