from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from memwing_benchmark.json_utils import parse_json_object


class ChatModelClient(Protocol):
    def complete_json(self, *, system: str, user: str, temperature: float = 0.0) -> dict: ...


class JudgeInput(BaseModel):
    case_id: str
    question: str
    expected_answer: str
    gold_evidence_ids: list[str] = Field(default_factory=list)
    agent_answer: str
    retrieved_evidence_ids: list[str] = Field(default_factory=list)


class JudgeResult(BaseModel):
    answer_score: int
    answer_correct: bool
    evidence_correct: bool
    temporal_correct: bool | None = None
    noise_polluted: bool
    reason: str = ""


def parse_judge_json(text: str) -> dict:
    return parse_json_object(text)


class LlmJudge:
    def __init__(self, model: ChatModelClient, *, temperature: float = 0.0) -> None:
        self.model = model
        self.temperature = temperature

    def evaluate(self, payload: JudgeInput) -> JudgeResult | None:
        system = "你是企业协作记忆系统评测员。只输出 JSON，不要输出解释性段落。"
        user = self._build_prompt(payload)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                request_user = user
                if attempt:
                    request_user += "\n\n上一次输出无法解析。请只输出符合 schema 的 JSON object。"
                raw = self.model.complete_json(
                    system=system, user=request_user, temperature=self.temperature
                )
                return JudgeResult.model_validate(raw)
            except Exception as exc:  # boundary: remote/model JSON can be malformed
                last_error = exc
        if last_error:
            return None
        return None

    @staticmethod
    def _build_prompt(payload: JudgeInput) -> str:
        return f"""你是企业协作记忆系统评测员。请根据标准答案、gold evidence 和被测 Agent 回答进行判分。
只输出 JSON，不要输出解释性段落。

评分规则：
- answer_score: 0=错误或编造，1=部分正确，2=完全正确且没有冲突事实。
- answer_correct: 只有 answer_score=2 时为 true。
- evidence_correct: 回答依据是否与 gold_evidence_ids 一致；如果回答正确但证据错误，仍为 false。
- temporal_correct: 如果 case 不涉及新旧事实覆盖，输出 null；如果涉及，判断回答是否采用当前有效事实。
- noise_polluted: 如果回答被无关噪声影响，输出 true，否则 false。

输入：
case_id: {payload.case_id}
question: {payload.question}
expected_answer: {payload.expected_answer}
gold_evidence_ids: {payload.gold_evidence_ids}
agent_answer: {payload.agent_answer}
retrieved_evidence_ids: {payload.retrieved_evidence_ids}

输出 JSON schema:
{{
  "answer_score": 0,
  "answer_correct": false,
  "evidence_correct": false,
  "temporal_correct": null,
  "noise_polluted": false,
  "reason": "不超过80字的中文理由"
}}"""
