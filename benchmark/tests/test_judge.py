from memwing_benchmark.evaluators.llm_judge import JudgeInput, LlmJudge, parse_judge_json
from memwing_benchmark.schema import GoldMemory


class FakeModel:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def complete_json(self, *, system: str, user: str, temperature: float = 0.0) -> dict:
        return parse_judge_json(self.payload)


def test_parse_judge_json_accepts_fenced_object() -> None:
    payload = """```json
{"judge_type":"online_answer","case_id":"bs001","probe_id":"p1","answer":{"answer_score":2,"answer_correct":true,"evidence_correct":true,"temporal_correct":null,"noise_polluted":false},"reason":"命中"}
```"""

    parsed = parse_judge_json(payload)

    assert parsed["answer"]["answer_score"] == 2
    assert parsed["answer"]["answer_correct"] is True


def test_llm_judge_returns_typed_result() -> None:
    judge = LlmJudge(
        FakeModel(
            '{"judge_type":"online_answer","case_id":"bs001","probe_id":"bs001_p2",'
            '"retrieval":{"recall_at_1":null,"recall_at_3":null,"recall_at_5":null,'
            '"matched_gold_memory_ids":[],"missing_gold_memory_ids":[],"used_forbidden_facts":[]},'
            '"answer":{"answer_score":1,"answer_correct":false,"evidence_correct":false,'
            '"temporal_correct":null,"noise_polluted":false,"matched_gold_memory_ids":[],'
            '"missing_gold_memory_ids":["bs001_s3"],"used_forbidden_facts":[]},'
            '"confidence":0.8,"reason":"缺少时间"}'
        )
    )

    result = judge.evaluate(
        JudgeInput(
            judge_type="online_answer",
            case_id="bs001",
            probe_id="bs001_p2",
            question="什么时候验收？",
            gold_answer="2026-04-30 18:00",
            gold_memories=[
                GoldMemory(
                    id="bs001_s3",
                    time="2026-04-25T09:40:00+08:00",
                    fact="最终验收截止时间为 2026-04-30 18:00。",
                )
            ],
            agent_answer="4月30日",
        )
    )

    assert result.answer_score == 1
    assert result.answer_correct is False
    assert result.reason == "缺少时间"
