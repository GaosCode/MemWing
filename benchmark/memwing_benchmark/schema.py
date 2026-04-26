from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from memwing_benchmark.json_utils import loads_json


class SeedMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    time: str | None = None
    sender: str | None = None
    message_type: str = "text"
    content: str
    source: str | None = None
    evidence_id: str | None = None
    should_write_memory: bool = True

    @property
    def message_id(self) -> str:
        return self.id


class Probe(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    question: str
    gold_answer: str
    must_include: list[str] = Field(default_factory=list)
    must_include_aliases: dict[str, list[str]] = Field(default_factory=dict)
    must_not_include: list[str] = Field(default_factory=list)
    gold_evidence_ids: list[str] = Field(default_factory=list)
    old_evidence_ids: list[str] = Field(default_factory=list)
    evidence_match: Literal["all", "any"] = "all"
    metrics: list[str] = Field(default_factory=list)
    temporal_expectation: str | None = None
    judge_rubric: str | None = None

    @property
    def probe_id(self) -> str:
        return self.id


class ExpectedMemoryItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    fact: str
    gold_evidence_ids: list[str] = Field(default_factory=list)


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    category: str
    difficulty: str | None = None
    case_time: str | None = None
    seed_messages: list[SeedMessage] = Field(default_factory=list)
    probes: list[Probe] = Field(default_factory=list)
    expected_memory_items: list[ExpectedMemoryItem] = Field(default_factory=list)
    reset_scope: str | None = None


class GoldMemory(BaseModel):
    id: str
    time: str | None = None
    fact: str


class TokenUsage(BaseModel):
    input: int | None = None
    output: int | None = None
    total: int | None = None
    source: str = "openclaw_trajectory"
    available: bool = False
    missing_reason: str | None = None


class Observability(BaseModel):
    memory_write_latency_ms: int | None = None
    memory_availability_latency_ms: int | None = None
    memory_write_tokens: int | None = None
    memory_recall_latency_ms: int | None = None
    memory_recall_tokens: int | None = None
    answer_latency_ms: int | None = None
    notes: list[str] = Field(default_factory=list)


class CommandRecord(BaseModel):
    command: list[str]
    cwd: str | None = None
    exit_code: int
    stdout: str = ""
    stderr: str = ""


class NormalizedResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    backend: str
    case_id: str
    probe_id: str
    chat_id: str | None
    seed_message_ids: list[str] = Field(default_factory=list)
    probe_message_id: str | None = None
    reply_message_id: str | None = None
    question: str
    answer: str
    expected_answer: str
    gold_evidence_ids: list[str] = Field(default_factory=list)
    retrieved_evidence_ids: list[str] = Field(default_factory=list)
    retrieved_contexts: list[str] = Field(default_factory=list)
    retrieval_recall_at_1: bool | None = None
    retrieval_recall_at_3: bool | None = None
    retrieval_recall_at_5: bool | None = None
    actual_tool_recall_at_1: bool | None = None
    actual_tool_recall_at_3: bool | None = None
    actual_tool_recall_at_5: bool | None = None
    answer_score: int | None = None
    answer_correct: bool | None = None
    temporal_correct: bool | None = None
    evidence_correct: bool | None = None
    noise_polluted: bool | None = None
    seed_completed_at: str | None = None
    first_memory_available_at: str | None = None
    probe_sent_at: str | None = None
    answer_received_at: str | None = None
    memory_availability_latency_ms: int | None = None
    latency_ms: int | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    observability: Observability = Field(default_factory=Observability)
    raw: dict[str, Any] = Field(default_factory=dict)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = loads_json(stripped)
        if not isinstance(parsed, dict):
            raise ValueError(f"{path} contains a non-object JSONL row")
        rows.append(parsed)
    return rows


def load_cases(path: Path, case_id: str | None = None) -> list[BenchmarkCase]:
    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(path)

    if path.is_dir():
        raw_cases: list[dict[str, Any]] = []
        for case_path in sorted(path.glob("*.json")):
            parsed = loads_json(case_path.read_bytes())
            if isinstance(parsed, list):
                raw_cases.extend(parsed)
            elif isinstance(parsed, dict):
                raw_cases.append(parsed)
            else:
                raise ValueError(f"{case_path} must contain a JSON object or array")
    elif path.suffix == ".jsonl":
        raw_cases = _load_jsonl(path)
    else:
        parsed = loads_json(path.read_bytes())
        if isinstance(parsed, list):
            raw_cases = parsed
        elif isinstance(parsed, dict):
            raw_cases = [parsed]
        else:
            raise ValueError(f"{path} must contain a JSON object or array")

    cases = [BenchmarkCase.model_validate(item) for item in raw_cases]
    if case_id:
        cases = [case for case in cases if case.case_id == case_id]
        if not cases:
            raise ValueError(f"case_id not found: {case_id}")
    return cases


def iter_case_probes(cases: list[BenchmarkCase]):
    for case in cases:
        for probe in case.probes:
            yield case, probe
