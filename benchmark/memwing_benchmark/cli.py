from __future__ import annotations

import time
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

import typer

from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.channels.feishu_cli import FeishuCli
from memwing_benchmark.collectors.openclaw_trajectory import parse_trajectory_dir
from memwing_benchmark.config import apply_overrides, load_config, sanitize_config_for_run
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluators.exact import evaluate_exact
from memwing_benchmark.evaluators.llm_judge import JudgeInput, LlmJudge
from memwing_benchmark.metrics.retrieval import recall_at_k
from memwing_benchmark.models.volcengine_ark import VolcengineArkChatModel
from memwing_benchmark.report import write_run_outputs
from memwing_benchmark.schema import (
    BenchmarkCase,
    NormalizedResult,
    Observability,
    TokenUsage,
    iter_case_probes,
    load_cases,
    make_run_id,
    utc_now_iso,
)


app = typer.Typer(add_completion=False, invoke_without_command=True)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config_path: Path = typer.Option(Path("config.example.json"), "--config"),
    backend: str = typer.Option("openclaw-native", "--backend"),
    cases_path: Path = typer.Option(Path("cases.json"), "--cases"),
    case_id: str | None = typer.Option(None, "--case-id"),
    live: bool = typer.Option(False, "--live"),
    chat_id: str | None = typer.Option(None, "--chat-id"),
    create_chat: bool = typer.Option(False, "--create-chat"),
    configure_openclaw: bool = typer.Option(False, "--configure-openclaw"),
    restart_gateway: bool = typer.Option(False, "--restart-gateway"),
    yes: bool = typer.Option(False, "--yes"),
    runs_dir: Path | None = typer.Option(None, "--runs-dir"),
    trajectory_dir: Path | None = typer.Option(None, "--trajectory-dir"),
    message_interval_seconds: float = typer.Option(2.0, "--message-interval-seconds"),
    settle_seconds: float = typer.Option(2.0, "--settle-seconds"),
    reply_timeout_seconds: float = typer.Option(120.0, "--reply-timeout-seconds"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    try:
        run(
            config_path=config_path,
            backend=backend,
            cases_path=cases_path,
            case_id=case_id,
            live=live,
            chat_id=chat_id,
            create_chat=create_chat,
            configure_openclaw=configure_openclaw,
            restart_gateway=restart_gateway,
            yes=yes,
            runs_dir=runs_dir,
            trajectory_dir=trajectory_dir,
            message_interval_seconds=message_interval_seconds,
            settle_seconds=settle_seconds,
            reply_timeout_seconds=reply_timeout_seconds,
        )
    except BenchmarkError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


def run(
    *,
    config_path: Path,
    backend: str,
    cases_path: Path,
    case_id: str | None,
    live: bool,
    chat_id: str | None,
    create_chat: bool,
    configure_openclaw: bool,
    restart_gateway: bool,
    yes: bool,
    runs_dir: Path | None,
    trajectory_dir: Path | None,
    message_interval_seconds: float,
    settle_seconds: float,
    reply_timeout_seconds: float,
) -> Path:
    if backend != "openclaw-native":
        raise BenchmarkError("v1 only supports backend=openclaw-native")
    config = apply_overrides(
        load_config(config_path),
        runs_dir=runs_dir,
        chat_id=chat_id,
        trajectory_dir=trajectory_dir,
    )
    cases = load_cases(cases_path, case_id=case_id)
    run_id = make_run_id()
    run_dir = Path(config.paths.runs_dir).expanduser() / run_id
    started_at = utc_now_iso()

    adapter = OpenClawNativeAdapter(
        Path(config.paths.openclaw_repo_dir),
        agent_id=config.openclaw.agent_id,
        workspace_dir=config.openclaw.workspace_dir,
    )
    raw_records: dict[str, Any] = {
        "feishu": [],
        "feishu_commands": [],
        "openclaw": [],
        "side_effects": [],
    }
    actual_chat_id = config.feishu.chat_id
    if live:
        actual_chat_id = _prepare_live_chat(
            config=config,
            adapter=adapter,
            raw_records=raw_records,
            run_id=run_id,
            create_chat=create_chat,
            configure_openclaw=configure_openclaw,
            restart_gateway=restart_gateway,
            yes=yes,
        )

    judge = _build_judge(config)
    results = (
        _run_live(
            run_id=run_id,
            backend=backend,
            cases=cases,
            config=config,
            adapter=adapter,
            chat_id=actual_chat_id,
            judge=judge,
            raw_records=raw_records,
            message_interval_seconds=message_interval_seconds,
            settle_seconds=settle_seconds,
            reply_timeout_seconds=reply_timeout_seconds,
            yes=yes,
        )
        if live
        else _run_offline(run_id=run_id, backend=backend, cases=cases, config=config, judge=judge)
    )
    raw_records["openclaw"] = [command.model_dump(mode="json") for command in adapter.commands]
    finished_at = utc_now_iso()
    run_config = {
        "benchmark_version": "v1",
        "backend": backend,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "case_file": str(cases_path),
        "case_ids": [case.case_id for case in cases],
        "chat_id": actual_chat_id,
        "live": live,
        "config": sanitize_config_for_run(config),
        "side_effects": raw_records["side_effects"],
    }
    write_run_outputs(
        run_dir=run_dir, run_config=run_config, results=results, raw_records=raw_records
    )
    typer.echo(str(run_dir))
    return run_dir


def _prepare_live_chat(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    run_id: str,
    create_chat: bool,
    configure_openclaw: bool,
    restart_gateway: bool,
    yes: bool,
) -> str:
    chat_id = config.feishu.chat_id
    feishu = FeishuCli(config.feishu.cli_bin)
    required_scopes = _required_feishu_scopes(
        will_create_chat=not config.feishu.chat_id
        and (create_chat or config.feishu.create_chat_if_missing)
    )
    feishu.ensure_ready(required_scopes=required_scopes)
    if not chat_id:
        if not (create_chat or config.feishu.create_chat_if_missing):
            raise BenchmarkError("live run requires --chat-id or create_chat_if_missing=true")
        _confirm_side_effect("创建飞书测试群并邀请机器人", yes)
        cli_bot_app_id = feishu.current_app_id()
        created = feishu.create_chat(
            name=f"{config.feishu.chat_name_prefix} {run_id} OpenClaw",
            bot_app_ids=[config.feishu.bot_app_id, cli_bot_app_id],
        )
        chat_id = str(created["chat_id"])
        raw_records["side_effects"].append({"action": "create_chat", "chat_id": chat_id})
    if configure_openclaw or config.openclaw.configure_allowlist:
        _confirm_side_effect("修改 OpenClaw 飞书 group allowlist/config", yes)
        adapter.configure_feishu_group(chat_id)
        raw_records["side_effects"].append({"action": "configure_openclaw", "chat_id": chat_id})
    if restart_gateway or config.openclaw.restart_gateway:
        _confirm_side_effect("重启 OpenClaw gateway", yes)
        adapter.restart_gateway()
        raw_records["side_effects"].append({"action": "restart_gateway"})
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return chat_id


def _run_offline(
    *, run_id: str, backend: str, cases: list[BenchmarkCase], config, judge
) -> list[NormalizedResult]:
    results: list[NormalizedResult] = []
    for case, probe in iter_case_probes(cases):
        exact = evaluate_exact(probe, "", [])
        results.append(
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=config.feishu.chat_id or None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_evidence_ids=[],
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(available=False, missing_reason="non-live run"),
                memory_recall_latency_ms=None,
                eval_result=exact,
                raw={"mode": "offline"},
            )
        )
    return results


def _run_live(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    chat_id: str,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    message_interval_seconds: float,
    settle_seconds: float,
    reply_timeout_seconds: float,
    yes: bool,
) -> list[NormalizedResult]:
    feishu = FeishuCli(config.feishu.cli_bin)
    feishu.ensure_ready(required_scopes=_required_feishu_scopes(will_create_chat=False))
    if any(case.preseed_memories for case in cases):
        _confirm_side_effect(
            "向 OpenClaw workspace 写入 run-specific preseed memory 并重建索引", yes
        )
    preseed_path = adapter.preseed_long_term_memories(cases=cases, run_id=run_id)
    if preseed_path:
        raw_records["side_effects"].append(
            {"action": "preseed_openclaw_memory", "path": str(preseed_path)}
        )

    results: list[NormalizedResult] = []
    for case in cases:
        for seed in case.seed_messages:
            sent = feishu.send_text(
                chat_id=chat_id,
                text=seed.content,
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=seed.id,
                ),
            )
            raw_records["feishu"].append({"kind": "seed", "case_id": case.case_id, "result": sent})
            time.sleep(message_interval_seconds)
        if case.seed_messages:
            time.sleep(settle_seconds)

        for probe in case.probes:
            probe_text = f"{config.feishu.mention_text} {probe.question}".strip()
            probe_sent_at = utc_now_iso()
            sent_probe = feishu.send_text(
                chat_id=chat_id,
                text=probe_text,
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=probe.id,
                ),
            )
            raw_records["feishu"].append(
                {"kind": "probe", "case_id": case.case_id, "result": sent_probe}
            )
            reply = feishu.wait_for_bot_reply(
                chat_id=chat_id,
                since=probe_sent_at,
                bot_ids=[config.feishu.bot_open_id, config.feishu.bot_app_id],
                timeout_seconds=reply_timeout_seconds,
            )
            reply_received_at = utc_now_iso()
            answer = _message_text(reply)
            latency_ms = _latency_ms(probe_sent_at, reply_received_at)
            raw_records["feishu"].append(
                {"kind": "reply", "case_id": case.case_id, "result": reply}
            )

            retrieved_evidence = _safe_memory_search(adapter, probe.question)
            parsed_trajectory = parse_trajectory_dir(
                Path(config.openclaw.trajectory_dir) if config.openclaw.trajectory_dir else None
            )
            eval_result = _evaluate_answer(judge, case.case_id, probe, answer, retrieved_evidence)
            results.append(
                _result_from_eval(
                    run_id=run_id,
                    backend=backend,
                    case=case,
                    probe=probe,
                    chat_id=chat_id,
                    seed_message_ids=[message.id for message in case.seed_messages],
                    answer=answer,
                    retrieved_evidence_ids=retrieved_evidence,
                    actual_tool_evidence_ids=parsed_trajectory.evidence_ids,
                    latency_ms=latency_ms,
                    tokens=parsed_trajectory.tokens,
                    memory_recall_latency_ms=parsed_trajectory.memory_recall_latency_ms,
                    eval_result=eval_result,
                    raw={
                        "probe_send_result": sent_probe,
                        "reply": reply,
                        "trajectory_paths": [str(path) for path in parsed_trajectory.paths],
                        "trajectory_missing_reason": parsed_trajectory.missing_reason,
                    },
                )
            )
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return results


def _result_from_eval(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    probe,
    chat_id: str | None,
    seed_message_ids: list[str],
    answer: str,
    retrieved_evidence_ids: list[str],
    actual_tool_evidence_ids: list[str],
    latency_ms: int | None,
    tokens: TokenUsage,
    memory_recall_latency_ms: int | None,
    eval_result,
    raw: dict[str, Any],
) -> NormalizedResult:
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=probe.id,
        chat_id=chat_id,
        seed_message_ids=seed_message_ids,
        probe_message_id=_nested_str(raw, "probe_send_result", "message_id"),
        reply_message_id=_nested_str(raw, "reply", "message_id"),
        question=probe.question,
        answer=answer,
        expected_answer=probe.gold_answer,
        gold_evidence_ids=probe.gold_evidence_ids,
        retrieved_evidence_ids=retrieved_evidence_ids,
        retrieval_recall_at_1=recall_at_k(
            probe.gold_evidence_ids, retrieved_evidence_ids, 1, match=probe.evidence_match
        ),
        retrieval_recall_at_3=recall_at_k(
            probe.gold_evidence_ids, retrieved_evidence_ids, 3, match=probe.evidence_match
        ),
        retrieval_recall_at_5=recall_at_k(
            probe.gold_evidence_ids, retrieved_evidence_ids, 5, match=probe.evidence_match
        ),
        actual_tool_recall_at_1=recall_at_k(
            probe.gold_evidence_ids, actual_tool_evidence_ids, 1, match=probe.evidence_match
        )
        if actual_tool_evidence_ids
        else None,
        actual_tool_recall_at_3=recall_at_k(
            probe.gold_evidence_ids, actual_tool_evidence_ids, 3, match=probe.evidence_match
        )
        if actual_tool_evidence_ids
        else None,
        actual_tool_recall_at_5=recall_at_k(
            probe.gold_evidence_ids, actual_tool_evidence_ids, 5, match=probe.evidence_match
        )
        if actual_tool_evidence_ids
        else None,
        answer_score=eval_result.answer_score if eval_result else None,
        answer_correct=eval_result.answer_correct if eval_result else None,
        temporal_correct=eval_result.temporal_correct if eval_result else None,
        evidence_correct=eval_result.evidence_correct if eval_result else None,
        noise_polluted=eval_result.noise_polluted if eval_result else None,
        latency_ms=latency_ms,
        tokens=tokens,
        observability=Observability(
            memory_write_latency_ms=None,
            memory_write_tokens=None,
            memory_recall_latency_ms=memory_recall_latency_ms,
            memory_recall_tokens=None,
            answer_latency_ms=latency_ms,
            notes=[
                "OpenClaw native does not expose stable memory write latency/token usage.",
            ],
        ),
        raw=raw,
    )


def _build_judge(config) -> LlmJudge | None:
    if not config.judge.has_api_key:
        return None
    if config.judge.provider != "volcengine_ark":
        return None
    model = VolcengineArkChatModel(
        api_key=config.judge.api_key,
        base_url=config.judge.base_url,
        model=config.judge.model,
    )
    return LlmJudge(model, temperature=config.judge.temperature)


def _evaluate_answer(
    judge: LlmJudge | None, case_id: str, probe, answer: str, retrieved: list[str]
):
    if judge is not None:
        result = judge.evaluate(
            JudgeInput(
                case_id=case_id,
                question=probe.question,
                expected_answer=probe.gold_answer,
                gold_evidence_ids=probe.gold_evidence_ids,
                agent_answer=answer,
                retrieved_evidence_ids=retrieved,
            )
        )
        if result is not None:
            return result
    return evaluate_exact(probe, answer, retrieved)


def _safe_memory_search(adapter: OpenClawNativeAdapter, question: str) -> list[str]:
    try:
        return adapter.memory_search(question, max_results=5)
    except Exception:
        return []


def _message_text(message: dict[str, Any]) -> str:
    for key in ("content", "text", "body"):
        value = message.get(key)
        if isinstance(value, str):
            return value
    return ""


def _latency_ms(start_iso: str, end_iso: str) -> int | None:
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return int((end - start).total_seconds() * 1000)
    except Exception:
        return None


def _nested_str(data: dict[str, Any], outer: str, inner: str) -> str | None:
    value = data.get(outer)
    if isinstance(value, dict) and value.get(inner) is not None:
        return str(value[inner])
    return None


def _confirm_side_effect(description: str, yes: bool) -> None:
    if yes:
        return
    confirmed = typer.confirm(f"将执行外部副作用：{description}。是否继续？")
    if not confirmed:
        raise BenchmarkError(f"用户取消：{description}")


def _required_feishu_scopes(*, will_create_chat: bool) -> list[str]:
    scopes = ["im:message.send_as_user"]
    if will_create_chat:
        scopes.append("im:chat:create_by_user")
    return scopes


def make_idempotency_key(*, run_id: str, backend: str, case_id: str, item_id: str) -> str:
    raw = f"{run_id}:{backend}:{case_id}:{item_id}"
    digest = sha1(raw.encode("utf-8")).hexdigest()[:10]
    trace = _safe_key_part(f"{case_id}-{item_id}")
    key = f"mwb-{trace}-{digest}"
    if len(key) <= 50:
        return key
    prefix_budget = 50 - len("mwb--") - len(digest)
    return f"mwb-{trace[:prefix_budget].rstrip('-')}-{digest}"


def _safe_key_part(value: str) -> str:
    out = []
    previous_dash = False
    for char in value.lower():
        safe = char if char.isalnum() else "-"
        if safe == "-":
            if previous_dash:
                continue
            previous_dash = True
        else:
            previous_dash = False
        out.append(safe)
    return "".join(out).strip("-") or "item"
