from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.collectors.openclaw_trajectory import parse_trajectory_dir
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluation import (
    DurablePollResult,
    _evaluate_answer,
    _evaluate_retrieval,
    _memory_search_raw,
    _result_from_eval,
    _retrieval_hit,
    _safe_memory_search,
)
from memwing_benchmark.evaluators.llm_judge import JudgeResult, LlmJudge
from memwing_benchmark.live_workspace import LiveChatIds
from memwing_benchmark.openclaw_feishu import _new_feishu_cli
from memwing_benchmark.openclaw_idempotency import make_idempotency_key
from memwing_benchmark.run_records import _latency_ms
from memwing_benchmark.run_support import debug as _debug
from memwing_benchmark.run_support import required_feishu_scopes as _required_feishu_scopes
from memwing_benchmark.schema import BenchmarkCase, NormalizedResult, Probe, utc_now_iso


def _run_live(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    chats: LiveChatIds,
    judge: LlmJudge,
    raw_records: dict[str, Any],
    message_interval_seconds: float,
    settle_seconds: float,
    reply_timeout_seconds: float,
    memory_poll_interval_seconds: float,
    memory_timeout_seconds: float,
    yes: bool,
) -> list[NormalizedResult]:
    del yes
    _debug(raw_records, "检查 Feishu CLI 发送消息权限")
    feishu = _new_feishu_cli(config.feishu.cli_bin)
    feishu.ensure_ready(required_scopes=_required_feishu_scopes(will_create_chat=False))
    seed_chat_id = chats.seed_chat_id
    probe_chat_id = chats.probe_chat_id
    if seed_chat_id == probe_chat_id:
        raise BenchmarkError(
            "cross_chat_durable requires different feishu.seed_chat_id and feishu.probe_chat_id"
        )

    results: list[NormalizedResult] = []
    for case in cases:
        _debug(
            raw_records,
            "开始 live case",
            case_id=case.case_id,
            seed_chat_id=seed_chat_id,
            probe_chat_id=probe_chat_id,
        )
        seed_completed_at: str | None = None
        for message in case.seed_messages:
            _debug(
                raw_records,
                "发送 seed 消息",
                case_id=case.case_id,
                seed_message_id=message.id,
                chat_id=seed_chat_id,
            )
            sent_seed = feishu.send_text(
                chat_id=seed_chat_id,
                text=message.content,
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=message.id,
                ),
            )
            raw_records["feishu"].append(
                {
                    "kind": "seed",
                    "case_id": case.case_id,
                    "seed_message_id": message.id,
                    "chat_id": seed_chat_id,
                    "result": sent_seed,
                }
            )
            seed_completed_at = utc_now_iso()
            if message_interval_seconds > 0:
                time.sleep(message_interval_seconds)

        if case.seed_messages:
            seed_flush_sent_at = utc_now_iso()
            _debug(
                raw_records, "发送 seed flush 摘要请求", case_id=case.case_id, chat_id=seed_chat_id
            )
            sent_seed_flush = feishu.send_text(
                chat_id=seed_chat_id,
                text=_build_seed_flush_text(config.feishu.mention_text),
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=f"{case.case_id}_seed_flush",
                ),
            )
            raw_records["feishu"].append(
                {
                    "kind": "seed_flush",
                    "case_id": case.case_id,
                    "chat_id": seed_chat_id,
                    "result": sent_seed_flush,
                }
            )
            _debug(
                raw_records, "等待 seed flush 摘要回复", case_id=case.case_id, chat_id=seed_chat_id
            )
            seed_flush_reply = feishu.wait_for_bot_reply(
                chat_id=seed_chat_id,
                since=seed_flush_sent_at,
                bot_ids=[config.feishu.bot_open_id, config.feishu.bot_app_id],
                timeout_seconds=reply_timeout_seconds,
            )
            raw_records["feishu"].append(
                {
                    "kind": "seed_flush_reply",
                    "case_id": case.case_id,
                    "chat_id": seed_chat_id,
                    "result": seed_flush_reply,
                }
            )
            seed_flush_commit_sent_at = utc_now_iso()
            _debug(
                raw_records, "发送 seed flush 写入请求", case_id=case.case_id, chat_id=seed_chat_id
            )
            sent_seed_flush_commit = feishu.send_text(
                chat_id=seed_chat_id,
                text=_build_seed_flush_commit_text(config.feishu.mention_text),
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=f"{case.case_id}_seed_flush_commit",
                ),
            )
            raw_records["feishu"].append(
                {
                    "kind": "seed_flush_commit",
                    "case_id": case.case_id,
                    "chat_id": seed_chat_id,
                    "result": sent_seed_flush_commit,
                }
            )
            _debug(
                raw_records, "等待 seed flush 写入回复", case_id=case.case_id, chat_id=seed_chat_id
            )
            seed_flush_commit_reply = feishu.wait_for_bot_reply(
                chat_id=seed_chat_id,
                since=seed_flush_commit_sent_at,
                bot_ids=[config.feishu.bot_open_id, config.feishu.bot_app_id],
                timeout_seconds=reply_timeout_seconds,
            )
            raw_records["feishu"].append(
                {
                    "kind": "seed_flush_commit_reply",
                    "case_id": case.case_id,
                    "chat_id": seed_chat_id,
                    "result": seed_flush_commit_reply,
                }
            )
            seed_completed_at = utc_now_iso()

        if settle_seconds > 0:
            _debug(raw_records, "等待 seed settle", case_id=case.case_id, seconds=settle_seconds)
            time.sleep(settle_seconds)
        _debug(raw_records, "重建 OpenClaw memory index", case_id=case.case_id)
        adapter.memory_index()

        for probe in case.probes:
            _debug(raw_records, "轮询长期记忆", case_id=case.case_id, probe_id=probe.id)
            durable_result = _poll_durable_memory(
                adapter=adapter,
                judge=judge,
                case=case,
                probe=probe,
                poll_interval_seconds=memory_poll_interval_seconds,
                timeout_seconds=memory_timeout_seconds,
            )
            raw_records.setdefault("memory_polls", []).append(
                {
                    "case_id": case.case_id,
                    "probe_id": probe.id,
                    "attempts": durable_result.attempts,
                }
            )
            probe_text = f"{config.feishu.mention_text} {probe.question}".strip()
            probe_sent_at = utc_now_iso()
            _debug(
                raw_records,
                "发送 probe 问题",
                case_id=case.case_id,
                probe_id=probe.id,
                chat_id=probe_chat_id,
            )
            sent_probe = feishu.send_text(
                chat_id=probe_chat_id,
                text=probe_text,
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=probe.id,
                ),
            )
            raw_records["feishu"].append(
                {
                    "kind": "probe",
                    "case_id": case.case_id,
                    "chat_id": probe_chat_id,
                    "result": sent_probe,
                }
            )
            _debug(
                raw_records,
                "等待 probe 回复",
                case_id=case.case_id,
                probe_id=probe.id,
                chat_id=probe_chat_id,
            )
            reply = feishu.wait_for_bot_reply(
                chat_id=probe_chat_id,
                since=probe_sent_at,
                bot_ids=[config.feishu.bot_open_id, config.feishu.bot_app_id],
                timeout_seconds=reply_timeout_seconds,
            )
            reply_received_at = utc_now_iso()
            answer = _message_text(reply)
            latency_ms = _latency_ms(probe_sent_at, reply_received_at)
            raw_records["feishu"].append(
                {
                    "kind": "reply",
                    "case_id": case.case_id,
                    "chat_id": probe_chat_id,
                    "result": reply,
                }
            )

            parsed_trajectory = parse_trajectory_dir(
                Path(config.openclaw.trajectory_dir) if config.openclaw.trajectory_dir else None
            )
            answer_result = _evaluate_answer(
                judge=judge,
                case=case,
                probe=probe,
                answer=answer,
                retrieved_contexts=durable_result.retrieved_contexts,
            )
            results.append(
                _result_from_eval(
                    run_id=run_id,
                    backend=backend,
                    case=case,
                    probe=probe,
                    chat_id=probe_chat_id,
                    seed_message_ids=[message.id for message in case.seed_messages],
                    answer=answer,
                    retrieved_contexts=durable_result.retrieved_contexts,
                    retrieved_evidence_ids=[],
                    actual_tool_evidence_ids=parsed_trajectory.evidence_ids,
                    latency_ms=latency_ms,
                    tokens=parsed_trajectory.tokens,
                    memory_recall_latency_ms=parsed_trajectory.memory_recall_latency_ms,
                    retrieval_result=durable_result.retrieval_result,
                    answer_result=answer_result,
                    raw={
                        "mode": "cross_chat_durable",
                        "seed_chat_id": seed_chat_id,
                        "probe_chat_id": probe_chat_id,
                        "seed_completed_at": seed_completed_at,
                        "first_memory_available_at": durable_result.first_memory_available_at,
                        "durable_memory_available": durable_result.durable_memory_available,
                        "extraction_timeout": durable_result.extraction_timeout,
                        "probe_sent_at": probe_sent_at,
                        "answer_received_at": reply_received_at,
                        "probe_send_result": sent_probe,
                        "reply": reply,
                        "trajectory_paths": [str(path) for path in parsed_trajectory.paths],
                        "trajectory_missing_reason": parsed_trajectory.missing_reason,
                        "memory_search_error": durable_result.search_error,
                        "memory_poll_attempts": durable_result.attempts,
                    },
                )
            )
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return results

def _poll_durable_memory(
    *,
    adapter: OpenClawNativeAdapter,
    judge: LlmJudge,
    case: BenchmarkCase,
    probe: Probe,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> DurablePollResult:
    deadline = time.monotonic() + timeout_seconds
    attempts: list[dict[str, Any]] = []
    last_contexts: list[str] = []
    last_error: str | None = None
    last_result: JudgeResult | None = None

    while True:
        attempted_at = utc_now_iso()
        search = _safe_memory_search(adapter, probe.question)
        retrieved_contexts = search.details.contexts
        retrieval_result = _evaluate_retrieval(
            judge=judge,
            case=case,
            probe=probe,
            retrieved_contexts=retrieved_contexts,
        )
        hit = _retrieval_hit(retrieval_result)
        attempts.append(
            {
                "attempted_at": attempted_at,
                "retrieved_contexts": retrieved_contexts,
                **_memory_search_raw(search),
                "retrieval_judge": retrieval_result.model_dump(mode="json")
                if retrieval_result
                else None,
                "durable_memory_available": hit,
            }
        )
        last_contexts = retrieved_contexts
        last_error = search.error
        last_result = retrieval_result
        if hit:
            return DurablePollResult(
                retrieved_contexts=retrieved_contexts,
                search_error=search.error,
                retrieval_result=retrieval_result,
                first_memory_available_at=attempted_at,
                durable_memory_available=True,
                extraction_timeout=False,
                attempts=attempts,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return DurablePollResult(
                retrieved_contexts=last_contexts,
                search_error=last_error,
                retrieval_result=last_result,
                first_memory_available_at=None,
                durable_memory_available=False,
                extraction_timeout=True,
                attempts=attempts,
            )
        time.sleep(min(poll_interval_seconds, remaining))

def _message_text(message: dict[str, Any]) -> str:
    for key in ("content", "text", "body"):
        value = message.get(key)
        if isinstance(value, str):
            return value
    return ""

def _build_seed_flush_text(mention_text: str) -> str:
    mention = mention_text.strip()
    body = (
        "请只基于本群刚刚这组 benchmark seed 对话，整理一份可写入持久记忆的事实摘要。"
        "现在不要声称已经写入文件，也不要编造。"
        "保留项目名、人名、负责人、交付范围、验收人、截止时间、状态更新和明确约束。"
        "摘要末尾单独输出 MEMWING_SEED_FLUSH_READY。"
    )
    return f"{mention} {body}".strip()

def _build_seed_flush_commit_text(mention_text: str) -> str:
    mention = mention_text.strip()
    body = (
        "现在执行 seed 持久记忆 flush。请把上一条事实摘要和本群 seed 对话中可跨群、跨 session "
        "使用的事实写入 OpenClaw 持久记忆文件 memory/YYYY-MM-DD.md。只基于本群已经出现的消息，"
        "不要编造。写入完成后只回复 MEMWING_SEED_FLUSH_DONE。"
    )
    return f"{mention} {body}".strip()
