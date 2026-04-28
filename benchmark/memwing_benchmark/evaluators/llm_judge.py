from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from memwing_benchmark.json_utils import parse_json_object
from memwing_benchmark.schema import GoldMemory, Probe


class ChatModelClient(Protocol):
    def complete_json(self, *, system: str, user: str, temperature: float = 0.0) -> dict: ...


JudgeType = Literal["offline_retrieval", "online_answer", "memory_write"]


def parse_judge_json(text: str) -> dict:
    return parse_json_object(text)


class JudgeInput(BaseModel):
    judge_type: JudgeType
    case_id: str
    probe_id: str
    question: str
    gold_answer: str
    gold_memories: list[GoldMemory] = Field(default_factory=list)
    old_memories: list[GoldMemory] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    temporal_expectation: str | None = None
    judge_rubric: str | None = None
    retrieved_context: list[str] = Field(default_factory=list)
    written_context: list[str] = Field(default_factory=list)
    noise_memories: list[GoldMemory] = Field(default_factory=list)
    agent_answer: str = ""


class RetrievalJudgeBlock(BaseModel):
    recall_at_1: bool | None = None
    recall_at_3: bool | None = None
    recall_at_5: bool | None = None
    matched_gold_memory_ids: list[str] = Field(default_factory=list)
    missing_gold_memory_ids: list[str] = Field(default_factory=list)
    used_forbidden_facts: list[str] = Field(default_factory=list)


class AnswerJudgeBlock(BaseModel):
    answer_score: int | None = None
    answer_correct: bool | None = None
    evidence_correct: bool | None = None
    temporal_correct: bool | None = None
    noise_polluted: bool | None = None
    matched_gold_memory_ids: list[str] = Field(default_factory=list)
    missing_gold_memory_ids: list[str] = Field(default_factory=list)
    used_forbidden_facts: list[str] = Field(default_factory=list)


class WriteJudgeBlock(BaseModel):
    write_recall: float | None = None
    write_precision: float | None = None
    written_claim_count: int | None = None
    matched_expected_memory_ids: list[str] = Field(default_factory=list)
    missing_expected_memory_ids: list[str] = Field(default_factory=list)
    unexpected_facts: list[str] = Field(default_factory=list)
    noise_facts: list[str] = Field(default_factory=list)
    wrong_facts: list[str] = Field(default_factory=list)
    stale_facts: list[str] = Field(default_factory=list)


class JudgeResult(BaseModel):
    judge_type: JudgeType
    case_id: str
    probe_id: str
    retrieval: RetrievalJudgeBlock = Field(default_factory=RetrievalJudgeBlock)
    answer: AnswerJudgeBlock = Field(default_factory=AnswerJudgeBlock)
    write: WriteJudgeBlock = Field(default_factory=WriteJudgeBlock)
    confidence: float | None = None
    reason: str = ""

    @property
    def answer_score(self) -> int | None:
        return self.answer.answer_score

    @property
    def answer_correct(self) -> bool | None:
        return self.answer.answer_correct

    @property
    def evidence_correct(self) -> bool | None:
        return self.answer.evidence_correct

    @property
    def temporal_correct(self) -> bool | None:
        return self.answer.temporal_correct

    @property
    def noise_polluted(self) -> bool | None:
        return self.answer.noise_polluted


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

    def evaluate_retrieval(
        self,
        *,
        case_id: str,
        probe: Probe,
        gold_memories: list[GoldMemory],
        old_memories: list[GoldMemory],
        retrieved_context: list[str],
    ) -> JudgeResult | None:
        return self.evaluate(
            JudgeInput(
                judge_type="offline_retrieval",
                case_id=case_id,
                probe_id=probe.id,
                question=probe.question,
                gold_answer=probe.gold_answer,
                gold_memories=gold_memories,
                old_memories=old_memories,
                must_include=probe.must_include,
                must_not_include=probe.must_not_include,
                temporal_expectation=probe.temporal_expectation,
                judge_rubric=probe.judge_rubric,
                retrieved_context=retrieved_context,
            )
        )

    def evaluate_answer(
        self,
        *,
        case_id: str,
        probe: Probe,
        gold_memories: list[GoldMemory],
        old_memories: list[GoldMemory],
        retrieved_context: list[str],
        answer: str,
    ) -> JudgeResult | None:
        return self.evaluate(
            JudgeInput(
                judge_type="online_answer",
                case_id=case_id,
                probe_id=probe.id,
                question=probe.question,
                gold_answer=probe.gold_answer,
                gold_memories=gold_memories,
                old_memories=old_memories,
                must_include=probe.must_include,
                must_not_include=probe.must_not_include,
                temporal_expectation=probe.temporal_expectation,
                judge_rubric=probe.judge_rubric,
                retrieved_context=retrieved_context,
                agent_answer=answer,
            )
        )

    def evaluate_write(
        self,
        *,
        case_id: str,
        expected_memories: list[GoldMemory],
        noise_memories: list[GoldMemory],
        written_context: list[str],
        allowed_other_memories: list[GoldMemory] | None = None,
    ) -> JudgeResult | None:
        return self.evaluate(
            JudgeInput(
                judge_type="memory_write",
                case_id=case_id,
                probe_id=f"{case_id}_write",
                question="判断 OpenClaw 正常写入链路是否写出应长期记忆的事实。",
                gold_answer="",
                gold_memories=expected_memories,
                old_memories=allowed_other_memories or [],
                noise_memories=noise_memories,
                written_context=written_context,
            )
        )

    @staticmethod
    def _build_prompt(payload: JudgeInput) -> str:
        common = f"""输入：
case_id: {payload.case_id}
probe_id: {payload.probe_id}
question: {payload.question}
gold_answer: {payload.gold_answer}
gold_memories: {[memory.model_dump(mode="json") for memory in payload.gold_memories]}
old_memories: {[memory.model_dump(mode="json") for memory in payload.old_memories]}
must_include: {payload.must_include}
must_not_include: {payload.must_not_include}
temporal_expectation: {payload.temporal_expectation}
judge_rubric: {payload.judge_rubric}
"""
        schema = f"""输出 JSON schema:
{{
  "judge_type": "{payload.judge_type}",
  "case_id": "{payload.case_id}",
  "probe_id": "{payload.probe_id}",
  "retrieval": {{
    "recall_at_1": null,
    "recall_at_3": null,
    "recall_at_5": null,
    "matched_gold_memory_ids": [],
    "missing_gold_memory_ids": [],
    "used_forbidden_facts": []
  }},
  "answer": {{
    "answer_score": null,
    "answer_correct": null,
    "evidence_correct": null,
    "temporal_correct": null,
    "noise_polluted": null,
    "matched_gold_memory_ids": [],
    "missing_gold_memory_ids": [],
    "used_forbidden_facts": []
  }},
  "write": {{
    "write_recall": null,
    "write_precision": null,
    "written_claim_count": null,
    "matched_expected_memory_ids": [],
    "missing_expected_memory_ids": [],
    "unexpected_facts": [],
    "noise_facts": [],
    "wrong_facts": [],
    "stale_facts": []
  }},
  "confidence": 0.0,
  "reason": "不超过80字的中文理由"
}}"""
        if payload.judge_type == "offline_retrieval":
            return f"""你是企业协作记忆系统评测员。请判断检索结果 top-k 是否包含回答 probe 所需的 gold facts。
只输出 JSON，不要输出解释性段落。

判定规则：
- 不要求逐字匹配，不要求检索结果保留 evidence id。
- 语义等价且时间有效性一致，即视为命中。
- 只包含旧事实、冲突事实、无关事实，视为未命中。
- 对 fact_update / temporal_conflict，必须命中当前有效事实，不能只命中旧事实。
- recall_at_1/3/5 分别只看 retrieved_context 的前 1/3/5 条。
- matched_gold_memory_ids 只能填写 gold_memories 中的 id。

{common}
retrieved_context: {payload.retrieved_context}

{schema}"""
        if payload.judge_type == "memory_write":
            return f"""你是企业协作长期记忆写入评测员。请判断 OpenClaw 写入到 durable memory 文件中的新增内容是否覆盖应写事实，且没有写入噪声、错误或过期事实。
只输出 JSON，不要输出解释性段落。

判定规则：
- gold_memories 是应该写入长期记忆的事实。
- old_memories 是同批其他 case 的应写事实；它们出现在 written_context 中不算当前 case 命中，也不算 unexpected/noise。
- noise_memories 是 seed 中不应该写入长期记忆的噪声或临时信息。
- written_context 是本轮 memory artifact diff 中新增/变化的文本。
- matched_expected_memory_ids 只能填写 gold_memories 中的 id。
- missing_expected_memory_ids 填写未被 written_context 语义覆盖的 gold ids。
- unexpected_facts 填写新增内容中没有被 gold_memories 支撑的业务事实。
- noise_facts 填写来自 noise_memories 或明显无关 seed 噪声的写入。
- wrong_facts 填写与 seed/gold 冲突或编造的事实。
- stale_facts 填写被后续消息覆盖但仍写入的旧事实。
- write_recall = 命中的 gold memory 数 / gold memory 总数。
- write_precision = 正确且应该写入的事实数 / written_context 中事实总数；如果没有写入事实，输出 0。

{common}
noise_memories: {[memory.model_dump(mode="json") for memory in payload.noise_memories]}
written_context: {payload.written_context}

{schema}"""
        return f"""你是企业协作记忆系统评测员。请根据 gold facts、标准答案和被测 Agent 回答进行判分。
只输出 JSON，不要输出解释性段落。

评分规则：
- answer_score: 0=错误、未回答或编造，1=部分正确，2=完全正确且没有冲突事实。
- answer_correct: 只有 answer_score=2 时为 true。
- evidence_correct: 回答是否由 gold_memories 支撑；不要要求回答出现 evidence id。
- temporal_correct: 如果不涉及新旧事实覆盖，输出 null；如果涉及，判断回答是否采用当前有效事实。
- noise_polluted: 如果回答被无关噪声影响，输出 true，否则 false。
- 对 fact_update / temporal_conflict，使用旧事实作为当前事实必须判错。

{common}
retrieved_context: {payload.retrieved_context}
agent_answer: {payload.agent_answer}

{schema}"""
