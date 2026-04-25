from memwing_benchmark.evaluators.llm_judge import JudgeInput, LlmJudge, parse_judge_json


class FakeModel:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def complete_json(self, *, system: str, user: str, temperature: float = 0.0) -> dict:
        return parse_judge_json(self.payload)


def test_parse_judge_json_accepts_fenced_object() -> None:
    payload = """```json
{"answer_score":2,"answer_correct":true,"evidence_correct":true,"temporal_correct":null,"noise_polluted":false,"reason":"命中"}
```"""

    parsed = parse_judge_json(payload)

    assert parsed["answer_score"] == 2
    assert parsed["answer_correct"] is True


def test_llm_judge_returns_typed_result() -> None:
    judge = LlmJudge(
        FakeModel(
            '{"answer_score":1,"answer_correct":false,"evidence_correct":false,'
            '"temporal_correct":null,"noise_polluted":false,"reason":"缺少时间"}'
        )
    )

    result = judge.evaluate(
        JudgeInput(
            case_id="bs001",
            question="什么时候验收？",
            expected_answer="2026-04-30 18:00",
            gold_evidence_ids=["bs001_s3"],
            agent_answer="4月30日",
            retrieved_evidence_ids=[],
        )
    )

    assert result.answer_score == 1
    assert result.answer_correct is False
    assert result.reason == "缺少时间"
