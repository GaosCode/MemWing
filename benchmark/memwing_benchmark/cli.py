from __future__ import annotations

from dataclasses import dataclass
from difflib import ndiff
import time
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

import typer

from memwing_benchmark.adapters.memwing import (
    MemWingAdapter,
    memwing_case_scope,
)
from memwing_benchmark.adapters.openclaw_native import MemorySearchDetails, OpenClawNativeAdapter
from memwing_benchmark.channels.feishu_cli import FeishuCli
from memwing_benchmark.collectors.openclaw_trajectory import parse_trajectory_dir
from memwing_benchmark.config import (
    apply_overrides,
    load_config,
    sanitize_config_for_run,
    validate_config_for_backend,
)
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluators.llm_judge import JudgeResult, LlmJudge
from memwing_benchmark.metrics.retrieval import recall_at_k, unique_preserve_order
from memwing_benchmark.models.volcengine_ark import VolcengineArkChatModel
from memwing_benchmark.report import write_run_outputs
from memwing_benchmark.schema import (
    BenchmarkCase,
    GoldMemory,
    NormalizedResult,
    Observability,
    Probe,
    TokenUsage,
    iter_case_probes,
    load_cases,
    make_run_id,
    utc_now_iso,
)


app = typer.Typer(add_completion=False, invoke_without_command=True)

OPENCLAW_NATIVE_BACKEND = "openclaw-native"
MEMWING_LEGACY_BACKEND = "memwing"
MEMWING_HTTP_BACKEND = "memwing-http"
MEMWING_OPENCLAW_PLUGIN_BACKEND = "memwing-openclaw-plugin"
SUPPORTED_BACKENDS = {
    OPENCLAW_NATIVE_BACKEND,
    MEMWING_LEGACY_BACKEND,
    MEMWING_HTTP_BACKEND,
    MEMWING_OPENCLAW_PLUGIN_BACKEND,
}
MEMWING_CHANGED_FILE_METRICS_MISSING_REASON = (
    "MemWing backend is evaluated through HTTP search APIs, not local memory files."
)
MEMWING_PLUGIN_BASE_URL_CONFIG_PATH = "plugins.entries.memwing.config.memwingBaseUrl"
MEMWING_PLUGIN_ENABLED_CONFIG_PATH = "plugins.entries.memwing.enabled"
MEMWING_PLUGIN_CONVERSATION_ACCESS_CONFIG_PATH = (
    "plugins.entries.memwing.hooks.allowConversationAccess"
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config_path: Path = typer.Option(Path("config.example.json"), "--config"),
    backend: str = typer.Option("openclaw-native", "--backend"),
    mode: str = typer.Option("retrieval", "--mode"),
    phase: str = typer.Option("full", "--phase"),
    cases_path: Path = typer.Option(Path("datasets"), "--cases"),
    case_id: str | None = typer.Option(None, "--case-id"),
    live: bool = typer.Option(False, "--live"),
    batch: bool = typer.Option(False, "--batch"),
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
    memory_poll_interval_seconds: float = typer.Option(20.0, "--memory-poll-interval-seconds"),
    memory_timeout_seconds: float = typer.Option(60.0, "--memory-timeout-seconds"),
    pg_preseed_per_case: bool = typer.Option(False, "--pg-preseed-per-case"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    try:
        run(
            config_path=config_path,
            backend=backend,
            mode=mode,
            phase=phase,
            cases_path=cases_path,
            case_id=case_id,
            live=live,
            batch=batch,
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
            memory_poll_interval_seconds=memory_poll_interval_seconds,
            memory_timeout_seconds=memory_timeout_seconds,
            pg_preseed_per_case=pg_preseed_per_case,
        )
    except BenchmarkError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


def run(
    *,
    config_path: Path,
    backend: str,
    mode: str,
    phase: str,
    cases_path: Path,
    case_id: str | None,
    live: bool,
    batch: bool,
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
    memory_poll_interval_seconds: float,
    memory_timeout_seconds: float,
    pg_preseed_per_case: bool,
) -> Path:
    if backend not in SUPPORTED_BACKENDS:
        raise BenchmarkError(
            "--backend must be one of: openclaw-native, memwing-http, memwing-openclaw-plugin"
        )
    backend = _canonical_backend(backend)
    if mode not in {"retrieval", "write"}:
        raise BenchmarkError("--mode must be one of: retrieval, write")
    if phase not in {"full", "ingest", "evaluate"}:
        raise BenchmarkError("--phase must be one of: full, ingest, evaluate")
    if mode != "write" and phase != "full":
        raise BenchmarkError("--phase is only supported with --mode write")
    if mode == "retrieval" and live and batch:
        raise BenchmarkError("--mode retrieval --live currently supports a single case only")
    if backend == OPENCLAW_NATIVE_BACKEND and mode == "write" and phase in {"full", "ingest"} and not live:
        raise BenchmarkError("--mode write --phase full/ingest requires --live")
    if backend == OPENCLAW_NATIVE_BACKEND and mode == "write" and phase == "evaluate" and live:
        raise BenchmarkError("--mode write --phase evaluate reads local memory files; omit --live")
    if memory_poll_interval_seconds <= 0:
        raise BenchmarkError("--memory-poll-interval-seconds must be greater than 0")
    if memory_timeout_seconds < 0:
        raise BenchmarkError("--memory-timeout-seconds must be greater than or equal to 0")
    if pg_preseed_per_case and mode != "retrieval":
        raise BenchmarkError("--pg-preseed-per-case is only supported with --mode retrieval")
    if pg_preseed_per_case and backend not in {
        MEMWING_HTTP_BACKEND,
        MEMWING_OPENCLAW_PLUGIN_BACKEND,
    }:
        raise BenchmarkError(
            "--pg-preseed-per-case is only supported with --backend memwing-http or "
            "--backend memwing-openclaw-plugin"
        )
    config = apply_overrides(
        load_config(config_path),
        runs_dir=runs_dir,
        chat_id=chat_id,
        trajectory_dir=trajectory_dir,
    )
    validate_config_for_backend(config, backend=backend)
    cases = load_cases(cases_path, case_id=case_id)
    pg_cleanup_cases = load_cases(cases_path) if pg_preseed_per_case else []
    if not batch and len(cases) != 1:
        raise BenchmarkError("non-batch runs require exactly one case; pass --case-id or --batch")
    run_id = make_run_id()
    run_mode = _run_mode_name(mode=mode, phase=phase, batch=batch)
    run_day = run_id.split("-", 1)[0]
    run_dir = Path(config.paths.runs_dir).expanduser() / run_mode / run_day / run_id
    started_at = utc_now_iso()

    raw_records: dict[str, Any] = {
        "feishu": [],
        "feishu_commands": [],
        "memwing": [],
        "memwing_http_health": [],
        "memwing_http_search": [],
        "openclaw_plugin_tool_evidence": [],
        "pg_preseed": [],
        "memwing_ingest": [],
        "memwing_pipeline_drains": [],
        "memwing_readiness": [],
        "memwing_polls": [],
        "openclaw": [],
        "memory_polls": [],
        "memory_searches": [],
        "side_effects": [],
        "debug": [],
    }
    judge = _build_judge(config)
    if live and judge is None and not (mode == "write" and phase == "ingest"):
        raise BenchmarkError("live benchmark requires a configured judge api key")
    if mode == "write" and phase == "evaluate" and judge is None:
        raise BenchmarkError("--mode write --phase evaluate requires a configured judge api key")

    live_chats = LiveChatIds(
        seed_chat_id=config.feishu.seed_chat_id or config.feishu.chat_id,
        probe_chat_id=config.feishu.probe_chat_id or config.feishu.chat_id,
    )
    if backend == MEMWING_HTTP_BACKEND:
        if live:
            raise BenchmarkError("--backend memwing-http does not support --live yet")
        adapter = MemWingAdapter(config.memwing)
        _preflight_memwing_http(adapter=adapter, raw_records=raw_records)
        if mode == "retrieval":
            results = _run_memwing_retrieval_batch(
                run_id=run_id,
                backend=backend,
                cases=cases,
                adapter=adapter,
                judge=judge,
                raw_records=raw_records,
                poll_interval_seconds=config.memwing.poll_interval_seconds,
                timeout_seconds=config.memwing.poll_timeout_seconds,
                yes=yes,
                ingest_seed_events=False,
                config=config,
                pg_preseed_per_case=pg_preseed_per_case,
                pg_cleanup_cases=pg_cleanup_cases,
            )
        elif phase == "ingest":
            results = _run_memwing_write_ingest_batch(
                run_id=run_id,
                backend=backend,
                cases=cases,
                adapter=adapter,
                raw_records=raw_records,
                yes=yes,
            )
        elif phase == "evaluate":
            results = _run_memwing_write_evaluate_batch(
                run_id=run_id,
                backend=backend,
                cases=cases,
                adapter=adapter,
                judge=judge,
                raw_records=raw_records,
            )
        else:
            raise BenchmarkError("--backend memwing-http write currently supports --phase ingest or evaluate")
        _record_memwing_http_records(raw_records, adapter.records)
        finished_at = utc_now_iso()
        run_config = {
            "benchmark_version": "v1",
            "backend": backend,
            "mode": mode,
            "phase": phase,
            "run_id": run_id,
            "run_mode": run_mode,
            "run_day": run_day,
            "started_at": started_at,
            "finished_at": finished_at,
            "case_file": str(cases_path),
            "case_ids": [case.case_id for case in cases],
            "batch": batch,
            "chat_id": None,
            "seed_chat_id": None,
            "probe_chat_id": None,
            "live": live,
            "pg_preseed_per_case": pg_preseed_per_case,
            **_memwing_pipeline_run_config(pg_preseed_per_case=pg_preseed_per_case),
            "config": sanitize_config_for_run(config),
            "side_effects": raw_records["side_effects"],
        }
        write_run_outputs(
            run_dir=run_dir,
            run_config=run_config,
            results=results,
            raw_records=raw_records,
        )
        typer.echo(str(run_dir))
        return run_dir

    adapter = OpenClawNativeAdapter(
        Path(config.paths.openclaw_repo_dir),
        agent_id=config.openclaw.agent_id,
        workspace_dir="" if batch or mode == "write" else config.openclaw.workspace_dir,
    )
    if backend == MEMWING_OPENCLAW_PLUGIN_BACKEND:
        _preflight_memwing_openclaw_plugin(
            config=config,
            adapter=adapter,
            raw_records=raw_records,
        )
        if live and mode == "retrieval":
            raise BenchmarkError(
                "--backend memwing-openclaw-plugin --mode retrieval uses MemWing APIs; omit --live"
            )
        memwing_adapter = MemWingAdapter(config.memwing)
        _preflight_memwing_http(adapter=memwing_adapter, raw_records=raw_records)
        if mode == "retrieval":
            results = _run_memwing_retrieval_batch(
                run_id=run_id,
                backend=backend,
                cases=cases,
                adapter=memwing_adapter,
                judge=judge,
                raw_records=raw_records,
                poll_interval_seconds=config.memwing.poll_interval_seconds,
                timeout_seconds=config.memwing.poll_timeout_seconds,
                yes=yes,
                ingest_seed_events=False,
                config=config,
                pg_preseed_per_case=pg_preseed_per_case,
                pg_cleanup_cases=pg_cleanup_cases,
            )
            _record_memwing_http_records(
                raw_records, memwing_adapter.records, openclaw_plugin=True
            )
            raw_records["openclaw"] = [
                command.model_dump(mode="json") for command in adapter.commands
            ]
            finished_at = utc_now_iso()
            run_config = {
                "benchmark_version": "v1",
                "backend": backend,
                "mode": mode,
                "phase": phase,
                "run_id": run_id,
                "run_mode": run_mode,
                "run_day": run_day,
                "started_at": started_at,
                "finished_at": finished_at,
                "case_file": str(cases_path),
                "case_ids": [case.case_id for case in cases],
                "batch": batch,
                "chat_id": None,
                "seed_chat_id": None,
                "probe_chat_id": None,
                "live": live,
                "pg_preseed_per_case": pg_preseed_per_case,
                **_memwing_pipeline_run_config(pg_preseed_per_case=pg_preseed_per_case),
                "config": sanitize_config_for_run(config),
                "side_effects": raw_records["side_effects"],
            }
            write_run_outputs(
                run_dir=run_dir,
                run_config=run_config,
                results=results,
                raw_records=raw_records,
            )
            typer.echo(str(run_dir))
            return run_dir
        if phase == "full":
            raise BenchmarkError(
                "--backend memwing-openclaw-plugin currently supports --phase ingest or evaluate"
            )
        if phase == "ingest" and not live:
            raise BenchmarkError("--backend memwing-openclaw-plugin --phase ingest requires --live")
        if phase == "evaluate":
            if live:
                raise BenchmarkError(
                    "--backend memwing-openclaw-plugin --phase evaluate uses MemWing APIs; omit --live"
                )
            results = _run_memwing_write_evaluate_batch(
                run_id=run_id,
                backend=backend,
                cases=cases,
                adapter=memwing_adapter,
                judge=judge,
                raw_records=raw_records,
            )
            _record_memwing_http_records(
                raw_records, memwing_adapter.records, openclaw_plugin=True
            )
            raw_records["openclaw"] = [
                command.model_dump(mode="json") for command in adapter.commands
            ]
            finished_at = utc_now_iso()
            run_config = {
                "benchmark_version": "v1",
                "backend": backend,
                "mode": mode,
                "phase": phase,
                "run_id": run_id,
                "run_mode": run_mode,
                "run_day": run_day,
                "started_at": started_at,
                "finished_at": finished_at,
                "case_file": str(cases_path),
                "case_ids": [case.case_id for case in cases],
                "batch": batch,
                "chat_id": None,
                "seed_chat_id": None,
                "probe_chat_id": None,
                "live": live,
                "config": sanitize_config_for_run(config),
                "side_effects": raw_records["side_effects"],
            }
            write_run_outputs(
                run_dir=run_dir,
                run_config=run_config,
                results=results,
                raw_records=raw_records,
            )
            typer.echo(str(run_dir))
            return run_dir
    workspace_restore: LiveWorkspaceRestore | None = None
    try:
        if live and mode == "retrieval":
            workspace_restore = _prepare_live_workspace(
                adapter=adapter,
                raw_records=raw_records,
                run_dir=run_dir,
                force_memory_flush=True,
                yes=yes,
            )
        if live:
            if mode == "write":
                live_chats = _prepare_write_ingest_chat(
                    config=config,
                    adapter=adapter,
                    raw_records=raw_records,
                    run_id=run_id,
                    create_chat=create_chat,
                    configure_openclaw=configure_openclaw,
                    restart_gateway=restart_gateway,
                    yes=yes,
                )
            else:
                live_chats = _prepare_live_chat(
                    config=config,
                    adapter=adapter,
                    raw_records=raw_records,
                    run_id=run_id,
                    create_chat=create_chat,
                    configure_openclaw=configure_openclaw,
                    restart_gateway=restart_gateway,
                    require_mention=True,
                    yes=yes,
                )

        if mode == "write":
            if phase == "ingest":
                if backend == MEMWING_OPENCLAW_PLUGIN_BACKEND:
                    memwing_adapter = MemWingAdapter(config.memwing)
                    _preflight_memwing_http(adapter=memwing_adapter, raw_records=raw_records)
                    results = _run_memwing_openclaw_plugin_write_ingest_batch(
                        run_id=run_id,
                        backend=backend,
                        cases=cases,
                        config=config,
                        openclaw_adapter=adapter,
                        memwing_adapter=memwing_adapter,
                        chats=live_chats,
                        raw_records=raw_records,
                        message_interval_seconds=message_interval_seconds,
                    )
                else:
                    results = _run_write_ingest_batch(
                        run_id=run_id,
                        backend=backend,
                        cases=cases,
                        config=config,
                        adapter=adapter,
                        chats=live_chats,
                        raw_records=raw_records,
                        message_interval_seconds=message_interval_seconds,
                    )
            elif phase == "evaluate":
                results = _run_write_evaluate_batch(
                    run_id=run_id,
                    backend=backend,
                    cases=cases,
                    adapter=adapter,
                    judge=judge,
                    raw_records=raw_records,
                    chat_id=live_chats.seed_chat_id,
                )
            else:
                results = _run_write_live_batch(
                    run_id=run_id,
                    backend=backend,
                    cases=cases,
                    config=config,
                    adapter=adapter,
                    chats=live_chats,
                    judge=judge,
                    raw_records=raw_records,
                    message_interval_seconds=message_interval_seconds,
                    settle_seconds=settle_seconds,
                    memory_poll_interval_seconds=memory_poll_interval_seconds,
                    memory_timeout_seconds=memory_timeout_seconds,
                )
        else:
            results = (
                _run_live(
                    run_id=run_id,
                    backend=backend,
                    cases=cases,
                    config=config,
                    adapter=adapter,
                    chats=live_chats,
                    judge=judge,
                    raw_records=raw_records,
                    message_interval_seconds=message_interval_seconds,
                    settle_seconds=settle_seconds,
                    reply_timeout_seconds=reply_timeout_seconds,
                    memory_poll_interval_seconds=memory_poll_interval_seconds,
                    memory_timeout_seconds=memory_timeout_seconds,
                    yes=yes,
                )
                if live
                else (
                    _run_offline_batch(
                        run_id=run_id,
                        backend=backend,
                        cases=cases,
                        config=config,
                        adapter=adapter,
                        judge=judge,
                        raw_records=raw_records,
                        run_dir=run_dir,
                        yes=yes,
                    )
                    if batch
                    else _run_offline(
                        run_id=run_id,
                        backend=backend,
                        cases=cases,
                        config=config,
                        adapter=adapter,
                        judge=judge,
                        raw_records=raw_records,
                        yes=yes,
                    )
                )
            )
    finally:
        if workspace_restore is not None:
            _restore_live_workspace(
                adapter=adapter,
                raw_records=raw_records,
                restore=workspace_restore,
            )
    raw_records["openclaw"] = [command.model_dump(mode="json") for command in adapter.commands]
    finished_at = utc_now_iso()
    run_config = {
        "benchmark_version": "v1",
        "backend": backend,
        "mode": mode,
        "phase": phase,
        "run_id": run_id,
        "run_mode": run_mode,
        "run_day": run_day,
        "started_at": started_at,
        "finished_at": finished_at,
        "case_file": str(cases_path),
        "case_ids": [case.case_id for case in cases],
        "batch": batch,
        "chat_id": live_chats.probe_chat_id,
        "seed_chat_id": live_chats.seed_chat_id,
        "probe_chat_id": live_chats.probe_chat_id,
        "live": live,
        "config": sanitize_config_for_run(config),
        "side_effects": raw_records["side_effects"],
    }
    write_run_outputs(
        run_dir=run_dir, run_config=run_config, results=results, raw_records=raw_records
    )
    typer.echo(str(run_dir))
    return run_dir


def _run_mode_name(*, mode: str, phase: str, batch: bool) -> str:
    suffix = "-batch" if batch else ""
    if mode == "write" and phase != "full":
        return f"write-{phase}{suffix}"
    return f"{mode}{suffix}"


def _canonical_backend(backend: str) -> str:
    if backend == MEMWING_LEGACY_BACKEND:
        return MEMWING_HTTP_BACKEND
    return backend


def _memwing_pipeline_run_config(*, pg_preseed_per_case: bool) -> dict[str, str]:
    if not pg_preseed_per_case:
        return {}
    return {
        "memory_pipeline": "real_ingest_per_case",
        "graph_backend": "graphiti",
        "evidence_backend": "qdrant",
    }


@dataclass(frozen=True)
class LiveChatIds:
    seed_chat_id: str
    probe_chat_id: str


@dataclass(frozen=True)
class LiveWorkspaceRestore:
    original_workspace: str
    memory_flush_touched: bool
    memory_flush_present: bool
    memory_flush_value: Any = None


@dataclass(frozen=True)
class DurablePollResult:
    retrieved_contexts: list[str]
    search_error: str | None
    retrieval_result: JudgeResult | None
    first_memory_available_at: str | None
    durable_memory_available: bool
    extraction_timeout: bool
    attempts: list[dict[str, Any]]


@dataclass(frozen=True)
class MemorySearchOutcome:
    details: MemorySearchDetails
    error: str | None = None


@dataclass(frozen=True)
class MemoryArtifactSnapshot:
    workspace: Path
    files: dict[str, str]
    captured_at: str


@dataclass(frozen=True)
class MemoryArtifactPollResult:
    before: MemoryArtifactSnapshot
    after: MemoryArtifactSnapshot
    changed_files: list[dict[str, Any]]
    first_changed_at: str | None
    timeout: bool


def _prepare_live_workspace(
    *,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    run_dir: Path,
    force_memory_flush: bool,
    yes: bool,
) -> LiveWorkspaceRestore:
    _debug(raw_records, "读取 OpenClaw 当前 workspace")
    original_workspace = adapter.get_default_workspace()
    original_memory_flush = None
    if force_memory_flush:
        _debug(raw_records, "读取 OpenClaw memoryFlush 配置", workspace=original_workspace)
        original_memory_flush = adapter.get_config_value("agents.defaults.compaction.memoryFlush")
    workspace_dir = run_dir / "openclaw-workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    _confirm_side_effect(
        "切换 OpenClaw 到本轮 benchmark 独立 workspace 并重启 gateway",
        yes,
    )
    _debug(raw_records, "切换 OpenClaw workspace", workspace=str(workspace_dir))
    adapter.set_default_workspace(workspace_dir)
    if force_memory_flush:
        next_memory_flush = (
            dict(original_memory_flush.value)
            if isinstance(original_memory_flush.value, dict)
            else {}
        )
        next_memory_flush["enabled"] = True
        next_memory_flush["forceFlushTranscriptBytes"] = 1
        _debug(raw_records, "写入 OpenClaw memoryFlush 配置", value=next_memory_flush)
        adapter.set_config_json("agents.defaults.compaction.memoryFlush", next_memory_flush)
    _debug(raw_records, "重启 OpenClaw gateway 以加载 workspace")
    adapter.restart_gateway()
    raw_records["side_effects"].append(
        {
            "action": "isolate_openclaw_workspace",
            "original_workspace": original_workspace,
            "workspace": str(workspace_dir),
        }
    )
    if original_memory_flush is not None:
        raw_records["side_effects"].append(
            {
                "action": "force_openclaw_memory_flush",
                "path": "agents.defaults.compaction.memoryFlush",
                "original_present": original_memory_flush.present,
            }
        )
    return LiveWorkspaceRestore(
        original_workspace=original_workspace,
        memory_flush_touched=original_memory_flush is not None,
        memory_flush_present=original_memory_flush.present if original_memory_flush else False,
        memory_flush_value=original_memory_flush.value if original_memory_flush else None,
    )


def _restore_live_workspace(
    *,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    restore: LiveWorkspaceRestore,
) -> None:
    _debug(raw_records, "恢复 OpenClaw workspace", workspace=restore.original_workspace)
    adapter.set_default_workspace(Path(restore.original_workspace))
    if restore.memory_flush_touched:
        if restore.memory_flush_present:
            _debug(
                raw_records,
                "恢复 OpenClaw memoryFlush 配置",
                value=restore.memory_flush_value,
            )
            adapter.set_config_json(
                "agents.defaults.compaction.memoryFlush",
                restore.memory_flush_value,
            )
        else:
            _debug(raw_records, "删除临时 OpenClaw memoryFlush 配置")
            adapter.unset_config_value("agents.defaults.compaction.memoryFlush")
    _debug(raw_records, "重启 OpenClaw gateway 以恢复原配置")
    adapter.restart_gateway()
    raw_records["side_effects"].append(
        {"action": "restore_openclaw_workspace", "workspace": restore.original_workspace}
    )
    if restore.memory_flush_touched:
        raw_records["side_effects"].append(
            {
                "action": "restore_openclaw_memory_flush",
                "path": "agents.defaults.compaction.memoryFlush",
                "restored_present": restore.memory_flush_present,
            }
        )


def _preflight_memwing_http(*, adapter: MemWingAdapter, raw_records: dict[str, Any]) -> None:
    health = getattr(adapter, "health", None)
    if callable(health):
        _debug(raw_records, "检查 MemWing HTTP readiness")
        health()
        _record_memwing_http_records(raw_records, adapter.records)


def _record_memwing_http_records(
    raw_records: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    openclaw_plugin: bool = False,
) -> None:
    raw_records["memwing"] = list(records)
    raw_records["memwing_http_health"] = [
        record for record in records if record.get("kind") == "health"
    ]
    raw_records["memwing_http_search"] = [
        record for record in records if record.get("kind") == "search"
    ]
    if openclaw_plugin:
        existing_evidence = raw_records.get("openclaw_plugin_tool_evidence", [])
        raw_records["openclaw_plugin_tool_evidence"] = existing_evidence or [
            record for record in records if record.get("kind") == "search"
        ]


def _require_openclaw_plugin_tool_evidence(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
) -> None:
    trajectory_dir = Path(config.openclaw.trajectory_dir) if config.openclaw.trajectory_dir else None
    evidence = adapter.collect_memwing_plugin_evidence(trajectory_dir=trajectory_dir)
    raw_records["openclaw_plugin_tool_evidence"] = evidence
    if not evidence:
        raise BenchmarkError("OpenClaw plugin MemWing tool evidence is unavailable")


def _preflight_memwing_openclaw_plugin(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
) -> None:
    _debug(raw_records, "检查 OpenClaw MemWing plugin 配置")
    enabled = adapter.get_config_value(MEMWING_PLUGIN_ENABLED_CONFIG_PATH)
    conversation_access = adapter.get_config_value(MEMWING_PLUGIN_CONVERSATION_ACCESS_CONFIG_PATH)
    base_url = adapter.get_config_value(MEMWING_PLUGIN_BASE_URL_CONFIG_PATH)
    raw_records.setdefault("openclaw_plugin_preflight", []).append(
        {
            "plugin_id": "memwing",
            "enabled_present": enabled.present,
            "enabled": enabled.value if isinstance(enabled.value, bool) else None,
            "conversation_access_present": conversation_access.present,
            "conversation_access": conversation_access.value
            if isinstance(conversation_access.value, bool)
            else None,
            "base_url_present": base_url.present,
            "base_url_matches_memwing": (
                _normalized_url(str(base_url.value)) == config.memwing.normalized_base_url
                if isinstance(base_url.value, str)
                else False
            ),
        }
    )
    if enabled.value is not True:
        raise BenchmarkError("OpenClaw MemWing plugin must be enabled")
    if conversation_access.value is not True:
        raise BenchmarkError(
            "OpenClaw MemWing plugin must enable hooks.allowConversationAccess"
        )
    if not isinstance(base_url.value, str) or not base_url.value.strip():
        raise BenchmarkError("OpenClaw MemWing plugin config memwingBaseUrl is required")
    if _normalized_url(base_url.value) != config.memwing.normalized_base_url:
        raise BenchmarkError("OpenClaw MemWing plugin config does not match memwing.base_url")


def _normalized_url(value: str) -> str:
    return value.strip().rstrip("/")


def _prepare_live_chat(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    run_id: str,
    create_chat: bool,
    configure_openclaw: bool,
    restart_gateway: bool,
    require_mention: bool,
    yes: bool,
) -> LiveChatIds:
    _debug(raw_records, "准备 Feishu live 群")
    feishu = FeishuCli(config.feishu.cli_bin)
    should_create = create_chat or config.feishu.create_chat_if_missing
    if not should_create:
        raise BenchmarkError(
            "formal live cross_chat_durable requires fresh seed/probe chats for every run; "
            "use --create-chat or set feishu.create_chat_if_missing=true"
        )
    required_scopes = _required_feishu_scopes(will_create_chat=True)
    _debug(raw_records, "检查 Feishu CLI 登录和 scope", scopes=required_scopes)
    feishu.ensure_ready(required_scopes=required_scopes)
    created_chat_ids: list[str] = []
    _confirm_side_effect("创建飞书 seed/probe 两个测试群并邀请机器人", yes)
    _debug(raw_records, "读取 Feishu CLI 当前 app id")
    cli_bot_app_id = feishu.current_app_id()
    _debug(raw_records, "Feishu CLI app id 已读取", cli_bot_app_id=cli_bot_app_id)
    seed_chat_id = _create_named_chat(
        feishu=feishu,
        config=config,
        run_id=run_id,
        role="Seed",
        cli_bot_app_id=cli_bot_app_id,
        raw_records=raw_records,
    )
    created_chat_ids.append(seed_chat_id)
    _debug(raw_records, "Seed 群创建完成", chat_id=seed_chat_id)
    probe_chat_id = _create_named_chat(
        feishu=feishu,
        config=config,
        run_id=run_id,
        role="Probe",
        cli_bot_app_id=cli_bot_app_id,
        raw_records=raw_records,
    )
    created_chat_ids.append(probe_chat_id)
    _debug(raw_records, "Probe 群创建完成", chat_id=probe_chat_id)
    if seed_chat_id == probe_chat_id:
        raise BenchmarkError(
            "cross_chat_durable requires different feishu.seed_chat_id and feishu.probe_chat_id"
        )
    allowlist_chat_ids = (
        [seed_chat_id, probe_chat_id]
        if configure_openclaw or config.openclaw.configure_allowlist
        else created_chat_ids
    )
    if allowlist_chat_ids:
        _confirm_side_effect("修改 OpenClaw 飞书 group allowlist/config", yes)
        configured_chat_ids = unique_preserve_order(allowlist_chat_ids)
        _debug(raw_records, "配置 OpenClaw 飞书群 allowlist", chat_ids=configured_chat_ids)
        adapter.configure_feishu_groups(configured_chat_ids, require_mention=require_mention)
        for chat_id in configured_chat_ids:
            raw_records["side_effects"].append(
                {
                    "action": "configure_openclaw",
                    "chat_id": chat_id,
                    "require_mention": require_mention,
                }
            )
    if restart_gateway or config.openclaw.restart_gateway:
        _confirm_side_effect("重启 OpenClaw gateway", yes)
        _debug(raw_records, "重启 OpenClaw gateway 以加载群配置")
        adapter.restart_gateway()
        raw_records["side_effects"].append({"action": "restart_gateway"})
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return LiveChatIds(seed_chat_id=seed_chat_id, probe_chat_id=probe_chat_id)


def _prepare_write_ingest_chat(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    run_id: str,
    create_chat: bool,
    configure_openclaw: bool,
    restart_gateway: bool,
    yes: bool,
) -> LiveChatIds:
    _debug(raw_records, "准备 Feishu write ingest 群")
    feishu = FeishuCli(config.feishu.cli_bin)
    should_create = create_chat or config.feishu.create_chat_if_missing
    if should_create:
        required_scopes = _required_feishu_scopes(will_create_chat=True)
        _debug(raw_records, "检查 Feishu CLI 登录和 scope", scopes=required_scopes)
        feishu.ensure_ready(required_scopes=required_scopes)
        _confirm_side_effect("创建飞书 write ingest 测试群并邀请机器人", yes)
        _debug(raw_records, "读取 Feishu CLI 当前 app id")
        cli_bot_app_id = feishu.current_app_id()
        _debug(raw_records, "Feishu CLI app id 已读取", cli_bot_app_id=cli_bot_app_id)
        chat_id = _create_named_chat(
            feishu=feishu,
            config=config,
            run_id=run_id,
            role="Ingest",
            cli_bot_app_id=cli_bot_app_id,
            raw_records=raw_records,
        )
        _debug(raw_records, "Ingest 群创建完成", chat_id=chat_id)
    else:
        chat_id = config.feishu.seed_chat_id or config.feishu.chat_id
        if not chat_id:
            raise BenchmarkError(
                "write ingest requires --chat-id, feishu.chat_id, or --create-chat"
            )
        _debug(raw_records, "使用已有 Feishu write ingest 群", chat_id=chat_id)
        feishu.ensure_ready(required_scopes=_required_feishu_scopes(will_create_chat=False))

    if configure_openclaw or config.openclaw.configure_allowlist or should_create:
        _confirm_side_effect("修改 OpenClaw 飞书 group allowlist/config", yes)
        _debug(raw_records, "配置 OpenClaw 飞书 ingest 群 allowlist", chat_id=chat_id)
        adapter.configure_feishu_group(chat_id, require_mention=False)
        raw_records["side_effects"].append(
            {
                "action": "configure_openclaw",
                "chat_id": chat_id,
                "require_mention": False,
            }
        )
    if restart_gateway or config.openclaw.restart_gateway or should_create:
        _confirm_side_effect("重启 OpenClaw gateway", yes)
        _debug(raw_records, "重启 OpenClaw gateway 以加载 ingest 群配置")
        adapter.restart_gateway()
        raw_records["side_effects"].append({"action": "restart_gateway"})
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return LiveChatIds(seed_chat_id=chat_id, probe_chat_id=chat_id)


def _create_named_chat(
    *,
    feishu: FeishuCli,
    config,
    run_id: str,
    role: str,
    cli_bot_app_id: str,
    raw_records: dict[str, Any],
) -> str:
    _debug(
        raw_records,
        f"开始创建 {role} 群",
        name=f"{config.feishu.chat_name_prefix} {run_id} {role}",
        bot_app_ids=[config.feishu.bot_app_id, cli_bot_app_id],
    )
    created = feishu.create_chat(
        name=f"{config.feishu.chat_name_prefix} {run_id} {role}",
        bot_app_ids=[config.feishu.bot_app_id, cli_bot_app_id],
    )
    chat_id = str(created["chat_id"])
    raw_records["side_effects"].append(
        {"action": f"create_{role.lower()}_chat", "chat_id": chat_id}
    )
    return chat_id


def _run_offline(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    yes: bool,
) -> list[NormalizedResult]:
    if judge is None:
        _debug(
            raw_records,
            "离线检索跳过：judge api key unavailable",
            case_count=len(cases),
            probe_count=sum(len(case.probes) for case in cases),
        )
        return [
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=config.feishu.chat_id or None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_contexts=[],
                retrieved_evidence_ids=[],
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(available=False, missing_reason="judge api key unavailable"),
                memory_recall_latency_ms=None,
                retrieval_result=None,
                answer_result=None,
                raw={"mode": "offline", "missing_reason": "judge api key unavailable"},
            )
            for case, probe in iter_case_probes(cases)
        ]

    if any(case.seed_messages for case in cases):
        _debug(
            raw_records,
            "准备写入离线 preseed 并重建 OpenClaw memory index",
            case_count=len(cases),
            seed_message_count=sum(len(case.seed_messages) for case in cases),
        )
        _confirm_side_effect("向 OpenClaw workspace 写入 benchmark preseed memory 并重建索引", yes)
    preseed_path = adapter.preseed_long_term_memories(cases=cases, run_id=run_id)
    if preseed_path:
        _debug(raw_records, "离线 preseed 写入完成", path=str(preseed_path))
        raw_records["side_effects"].append(
            {"action": "preseed_openclaw_memory", "path": str(preseed_path)}
        )
    else:
        _debug(raw_records, "离线 preseed 无可写入内容", case_count=len(cases))

    results: list[NormalizedResult] = []
    for case, probe in iter_case_probes(cases):
        _debug(
            raw_records,
            "离线检索开始",
            case_id=case.case_id,
            probe_id=probe.id,
            query=probe.question,
        )
        search = _safe_memory_search(adapter, probe.question)
        search_raw = _memory_search_raw(search)
        _debug(
            raw_records,
            "离线检索完成",
            case_id=case.case_id,
            probe_id=probe.id,
            result_count=search_raw["memory_search_result_count"],
            latency_ms=search_raw["memory_search_latency_ms"],
            top_score=search_raw["memory_search_top_score"],
            top_path=search_raw["memory_search_top_path"],
            error=search.error,
        )
        raw_records.setdefault("memory_searches", []).append(
            {
                "mode": "offline",
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                **search_raw,
            }
        )
        retrieved_contexts = search.details.contexts
        retrieval_result = _evaluate_retrieval(
            judge=judge,
            case=case,
            probe=probe,
            retrieved_contexts=retrieved_contexts,
        )
        _debug(
            raw_records,
            "离线检索 judge 完成",
            case_id=case.case_id,
            probe_id=probe.id,
            recall_at_1=retrieval_result.retrieval.recall_at_1
            if retrieval_result
            else None,
            recall_at_3=retrieval_result.retrieval.recall_at_3
            if retrieval_result
            else None,
            recall_at_5=retrieval_result.retrieval.recall_at_5
            if retrieval_result
            else None,
            matched_gold_memory_ids=retrieval_result.retrieval.matched_gold_memory_ids
            if retrieval_result
            else [],
        )
        results.append(
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=config.feishu.chat_id or None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_contexts=retrieved_contexts,
                retrieved_evidence_ids=[],
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(available=False, missing_reason="non-live run"),
                memory_recall_latency_ms=None,
                retrieval_result=retrieval_result,
                answer_result=None,
                raw={
                    "mode": "offline",
                    **search_raw,
                },
            )
        )
    return results


def _run_offline_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    run_dir: Path,
    yes: bool,
) -> list[NormalizedResult]:
    del run_dir
    if judge is None:
        _debug(
            raw_records,
            "离线批量跳过：judge api key unavailable",
            case_count=len(cases),
        )
        return _run_offline(
            run_id=run_id,
            backend=backend,
            cases=cases,
            config=config,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            yes=yes,
        )

    _confirm_side_effect(
        "在当前 OpenClaw 默认 workspace 中按 case 写入对应 preseed memory 并重建索引",
        yes,
    )
    workspace = adapter.get_default_workspace()
    _debug(raw_records, "离线批量使用 OpenClaw 默认 workspace", workspace=workspace)
    results: list[NormalizedResult] = []
    raw_records["side_effects"].append(
        {"action": "use_default_openclaw_workspace_for_offline_batch", "workspace": workspace}
    )
    for case in cases:
        _debug(raw_records, "离线批量 case 开始", case_id=case.case_id, workspace=workspace)
        case_results = _run_offline(
            run_id=run_id,
            backend=backend,
            cases=[case],
            config=config,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            yes=True,
        )
        results.extend(case_results)
        _debug(
            raw_records,
            "离线批量 case 完成",
            case_id=case.case_id,
            probe_count=len(case.probes),
            result_count=len(case_results),
        )
        raw_records["side_effects"].append(
            {
                "action": "offline_batch_case_completed",
                "case_id": case.case_id,
                "workspace": workspace,
            }
        )
    return results


def _run_memwing_retrieval_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    poll_interval_seconds: float,
    timeout_seconds: float,
    yes: bool,
    ingest_seed_events: bool = True,
    config: Any | None = None,
    pg_preseed_per_case: bool = False,
    pg_cleanup_cases: list[BenchmarkCase] | None = None,
) -> list[NormalizedResult]:
    if poll_interval_seconds <= 0:
        raise BenchmarkError("memwing.poll_interval_seconds must be greater than 0")
    if timeout_seconds < 0:
        raise BenchmarkError("memwing.poll_timeout_seconds must be greater than or equal to 0")
    if ingest_seed_events and any(case.seed_messages for case in cases):
        _confirm_side_effect("向 MemWing HTTP ingest endpoint 写入 benchmark Source Events", yes)
    if pg_preseed_per_case:
        _confirm_side_effect(
            "通过 MemWing HTTP/OpenClaw ingest endpoint 写入 benchmark Source Events，"
            "并按 case scope 执行 cleanup 和 product pipeline await",
            yes,
        )
        return _run_memwing_real_ingest_retrieval_batch(
            run_id=run_id,
            backend=backend,
            cases=cases,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
        )

    results: list[NormalizedResult] = []
    for case in cases:
        _run_memwing_retrieval_case(
            run_id=run_id,
            backend=backend,
            case=case,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            ingest_seed_events=ingest_seed_events,
            results=results,
        )
    return results


def _run_memwing_real_ingest_retrieval_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
) -> list[NormalizedResult]:
    results: list[NormalizedResult] = []
    for case in cases:
        _run_memwing_real_ingest_retrieval_case(
            run_id=run_id,
            backend=backend,
            case=case,
            adapter=adapter,
            judge=judge,
            raw_records=raw_records,
            results=results,
        )
    return results


def _run_memwing_real_ingest_retrieval_case(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    results: list[NormalizedResult],
) -> None:
    scope = memwing_case_scope(config=adapter.config, run_id=run_id, case_id=case.case_id)
    _debug(
        raw_records,
        "MemWing real ingest retrieval case 开始",
        case_id=case.case_id,
        project_memory_space_id=scope.project_memory_space_id,
        seed_message_count=len(case.seed_messages),
        probe_count=len(case.probes),
    )

    _debug(raw_records, "MemWing benchmark scope cleanup 开始", case_id=case.case_id)
    cleanup = adapter.cleanup_benchmark_scope(scope)
    raw_records.setdefault("memwing_scope_cleanup", []).append(
        {"case_id": case.case_id, "scope": scope.payload(), "response": cleanup}
    )
    _debug(raw_records, "MemWing benchmark scope cleanup 完成", case_id=case.case_id)

    _debug(raw_records, "MemWing benchmark ingest 开始", case_id=case.case_id)
    ingest_records = adapter.ingest_seed_messages(case=case, run_id=run_id, scope=scope)
    seed_completed_at = utc_now_iso()
    raw_records.setdefault("memwing_ingest", []).extend(ingest_records)
    _debug(
        raw_records,
        "MemWing benchmark ingest 完成",
        case_id=case.case_id,
        accepted_count=sum(1 for record in ingest_records if record.get("accepted") is True),
    )

    expected_source_event_ids = _expected_source_event_ids_for_real_ingest(
        case=case,
        ingest_records=ingest_records,
    )
    _debug(
        raw_records,
        "MemWing product pipeline await 开始",
        case_id=case.case_id,
        expected_source_event_count=len(expected_source_event_ids),
    )
    readiness = adapter.pipeline_await(
        scope=scope,
        source_event_ids=expected_source_event_ids,
        profile="retrieval-evaluate",
    )
    raw_records.setdefault("memwing_pipeline_awaits", []).append(
        {
            "case_id": case.case_id,
            "scope": scope.payload(),
            "profile": "retrieval-evaluate",
            "response": readiness,
        }
    )
    if readiness.get("ready") is not True:
        raise BenchmarkError(f"MemWing pipeline await did not become ready: case_id={case.case_id}")
    _debug(raw_records, "MemWing product pipeline await 完成", case_id=case.case_id)

    for probe in case.probes:
        _debug(
            raw_records,
            "MemWing benchmark search 开始",
            case_id=case.case_id,
            probe_id=probe.id,
        )
        details = adapter.memory_search_details(probe.question, max_results=5, scope=scope)
        _debug(
            raw_records,
            "MemWing benchmark search 完成",
            case_id=case.case_id,
            probe_id=probe.id,
            result_count=len(details.results),
            latency_ms=details.latency_ms,
        )
        search_raw = _memory_search_raw(MemorySearchOutcome(details=details))
        raw_records.setdefault("memory_searches", []).append(
            {
                "mode": "memwing_real_ingest_retrieval",
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                **search_raw,
            }
        )
        retrieval_result = _evaluate_retrieval(
            judge=judge,
            case=case,
            probe=probe,
            retrieved_contexts=details.contexts,
        )
        results.append(
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_contexts=details.contexts,
                retrieved_evidence_ids=_source_event_ids_from_results(details.results),
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(
                    available=False,
                    missing_reason="non-live MemWing retrieval run",
                ),
                memory_recall_latency_ms=details.latency_ms,
                retrieval_result=retrieval_result,
                answer_result=None,
                raw={
                    "mode": "memwing_real_ingest_retrieval",
                    "seed_completed_at": seed_completed_at,
                    "expected_source_event_ids": expected_source_event_ids,
                    "readiness": readiness,
                    **search_raw,
                },
            )
        )


def _expected_source_event_ids_for_real_ingest(
    *,
    case: BenchmarkCase,
    ingest_records: list[dict[str, Any]],
) -> list[str]:
    source_event_ids = [
        source_event_id
        for record in ingest_records
        if isinstance(source_event_id := record.get("source_event_id"), str)
    ]
    if source_event_ids:
        return unique_preserve_order(source_event_ids)
    return [message.id for message in case.seed_messages]


def _run_memwing_retrieval_case(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    poll_interval_seconds: float,
    timeout_seconds: float,
    ingest_seed_events: bool,
    results: list[NormalizedResult],
) -> None:
    _debug(
        raw_records,
        "MemWing retrieval case 开始",
        case_id=case.case_id,
        seed_message_count=len(case.seed_messages),
        probe_count=len(case.probes),
    )
    ingest_records = (
        adapter.ingest_seed_messages(case=case, run_id=run_id) if ingest_seed_events else []
    )
    seed_completed_at = utc_now_iso()
    raw_records.setdefault("memwing_ingest", []).extend(ingest_records)
    source_event_ids_by_seed = {
        record["seed_message_id"]: record["source_event_id"]
        for record in ingest_records
        if isinstance(record.get("seed_message_id"), str)
        and isinstance(record.get("source_event_id"), str)
    }

    for probe in case.probes:
        expected_source_event_ids = (
            [
                source_event_ids_by_seed[evidence_id]
                for evidence_id in probe.gold_evidence_ids
                if evidence_id in source_event_ids_by_seed
            ]
            or [
                source_event_id
                for source_event_id in source_event_ids_by_seed.values()
                if source_event_id
            ]
            or ([] if ingest_seed_events else list(probe.gold_evidence_ids))
        )
        poll = _poll_memwing_readiness(
            adapter=adapter,
            query=probe.question,
            expected_source_event_ids=expected_source_event_ids,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            raw_records=raw_records,
            case_id=case.case_id,
            probe_id=probe.id,
        )
        raw_records.setdefault("memwing_polls", []).append(
            {
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                "expected_source_event_ids": expected_source_event_ids,
                "attempts": poll.attempts,
                "durable_memory_available": poll.durable_memory_available,
                "extraction_timeout": poll.extraction_timeout,
                "first_memory_available_at": poll.first_memory_available_at,
            }
        )
        poll_details = _details_from_poll(poll)
        search_raw = _memory_search_raw(
            MemorySearchOutcome(details=poll_details, error=poll.search_error)
        )
        raw_records.setdefault("memory_searches", []).append(
            {
                "mode": "memwing_retrieval",
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                **search_raw,
            }
        )
        retrieval_result = _evaluate_retrieval(
            judge=judge,
            case=case,
            probe=probe,
            retrieved_contexts=poll.retrieved_contexts,
        )
        results.append(
            _result_from_eval(
                run_id=run_id,
                backend=backend,
                case=case,
                probe=probe,
                chat_id=None,
                seed_message_ids=[message.id for message in case.seed_messages],
                answer="",
                retrieved_contexts=poll.retrieved_contexts,
                retrieved_evidence_ids=_source_event_ids_from_results(poll_details.results),
                actual_tool_evidence_ids=[],
                latency_ms=None,
                tokens=TokenUsage(
                    available=False,
                    missing_reason="non-live MemWing retrieval run",
                ),
                memory_recall_latency_ms=None,
                retrieval_result=retrieval_result,
                answer_result=None,
                raw={
                    "mode": "memwing_retrieval",
                    "seed_completed_at": seed_completed_at,
                    "first_memory_available_at": poll.first_memory_available_at,
                    "durable_memory_available": poll.durable_memory_available,
                    "extraction_timeout": poll.extraction_timeout,
                    "memory_poll_attempts": poll.attempts,
                    "expected_source_event_ids": expected_source_event_ids,
                    **search_raw,
                },
            )
        )

def _run_memwing_write_ingest_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    raw_records: dict[str, Any],
    yes: bool,
) -> list[NormalizedResult]:
    if any(case.seed_messages for case in cases):
        _confirm_side_effect("向 MemWing HTTP ingest endpoint 写入 benchmark Source Events", yes)

    results: list[NormalizedResult] = []
    for case in cases:
        _debug(
            raw_records,
            "MemWing write ingest case 开始",
            case_id=case.case_id,
            seed_message_count=len(case.seed_messages),
        )
        ingest_records = adapter.ingest_seed_messages(case=case, run_id=run_id)
        seed_completed_at = utc_now_iso()
        raw_records.setdefault("memwing_ingest", []).extend(ingest_records)
        raw_records.setdefault("memory_writes", []).append(
            {
                "phase": "ingest",
                "backend": backend,
                "case_id": case.case_id,
                "seed_message_count": len(case.seed_messages),
                "accepted_count": sum(1 for record in ingest_records if record.get("accepted") is True),
                "source_event_ids": [
                    record["source_event_id"]
                    for record in ingest_records
                    if isinstance(record.get("source_event_id"), str)
                ],
                "note": "MemWing ingest sends Source Events through the HTTP adapter; run --mode write --phase evaluate after indexing settles.",
            }
        )
        results.append(
            _result_from_write_ingest(
                run_id=run_id,
                backend=backend,
                case=case,
                chat_id=None,
                seed_message_ids=[message.id for message in case.seed_messages],
                seed_completed_at=seed_completed_at,
                raw_extra={
                    "backend": backend,
                    "ingest_records": ingest_records,
                },
                observability_note=(
                    "MemWing write ingest sends Source Events through HTTP; evaluate after indexing settles."
                ),
            )
        )
    return results


def _run_memwing_write_evaluate_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: MemWingAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
) -> list[NormalizedResult]:
    results: list[NormalizedResult] = []
    total_cases = len(cases)
    for index, case in enumerate(cases, start=1):
        expected_memories = _expected_memories(case)
        noise_memories = _noise_memories(case)
        allowed_other_memories = _expected_memories_for_other_cases(cases, case.case_id)
        _debug(
            raw_records,
            "MemWing write evaluate case 开始",
            case_id=case.case_id,
            case_index=index,
            case_count=total_cases,
            expected_memory_count=len(expected_memories),
            noise_memory_count=len(noise_memories),
            allowed_other_memory_count=len(allowed_other_memories),
        )
        readiness_unavailable = {
            "profile": "write-evaluate",
            "available": False,
            "reason": "source_event_ids_required",
        }
        raw_records.setdefault("memwing_pipeline_awaits", []).append(
            {
                "case_id": case.case_id,
                "profile": "write-evaluate",
                "available": False,
                "reason": "source_event_ids_required",
            }
        )
        searches: list[dict[str, Any]] = []
        written_contexts: list[str] = []
        search_latencies: list[int] = []
        search_errors: list[str] = []
        for item in case.expected_memory_items:
            search = _safe_memory_search(adapter, item.fact)
            search_raw = _memory_search_raw(search)
            if search.error:
                search_errors.append(search.error)
            search_latencies.append(search.details.latency_ms)
            written_contexts.extend(search.details.contexts)
            searches.append(
                {
                    "case_id": case.case_id,
                    "expected_memory_id": item.id,
                    "query": item.fact,
                    **search_raw,
                }
            )
            raw_records.setdefault("memory_searches", []).append(
                {
                    "mode": "memwing_write_evaluate",
                    "case_id": case.case_id,
                    "expected_memory_id": item.id,
                    "query": item.fact,
                    **search_raw,
                }
            )
        written_contexts = unique_preserve_order(written_contexts)
        _debug(
            raw_records,
            "MemWing write evaluate search 完成",
            case_id=case.case_id,
            written_context_count=len(written_contexts),
            search_error_count=len(search_errors),
        )
        write_result = _evaluate_write(
            judge=judge,
            case_id=case.case_id,
            expected_memories=expected_memories,
            noise_memories=noise_memories,
            written_contexts=written_contexts,
            allowed_other_memories=allowed_other_memories,
        )
        raw_records.setdefault("memory_writes", []).append(
            {
                "phase": "evaluate",
                "backend": backend,
                "case_id": case.case_id,
                "searches": searches,
                "written_context_count": len(written_contexts),
                "changed_file_metrics_available": False,
                "changed_file_metrics_missing_reason": MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
                "readiness_unavailable": readiness_unavailable,
                "write_judge": write_result.model_dump(mode="json") if write_result else None,
            }
        )
        results.append(
            _result_from_memwing_write(
                run_id=run_id,
                backend=backend,
                case=case,
                seed_message_ids=[message.id for message in case.seed_messages],
                written_contexts=written_contexts,
                search_latencies=search_latencies,
                search_errors=search_errors,
                write_result=write_result,
                searches=searches,
                readiness_summary=readiness_unavailable,
            )
        )
    return results


def _poll_memwing_readiness(
    *,
    adapter: MemWingAdapter,
    query: str,
    expected_source_event_ids: list[str],
    poll_interval_seconds: float,
    timeout_seconds: float,
    raw_records: dict[str, Any] | None = None,
    case_id: str | None = None,
    probe_id: str | None = None,
) -> DurablePollResult:
    deadline = time.monotonic() + timeout_seconds
    attempts: list[dict[str, Any]] = []
    last_details = MemorySearchDetails(contexts=[], results=[], latency_ms=0, raw=None)
    last_error: str | None = None

    while True:
        attempted_at = utc_now_iso()
        search = _safe_memory_search(adapter, query)
        details = search.details
        retrieved_source_event_ids = _source_event_ids_from_results(details.results)
        matched_source_event_ids = [
            source_event_id
            for source_event_id in expected_source_event_ids
            if source_event_id in retrieved_source_event_ids
        ]
        hit = bool(expected_source_event_ids and matched_source_event_ids)
        attempts.append(
            {
                "attempted_at": attempted_at,
                "expected_source_event_ids": expected_source_event_ids,
                "retrieved_source_event_ids": retrieved_source_event_ids,
                "matched_source_event_ids": matched_source_event_ids,
                **_memory_search_raw(search),
                "durable_memory_available": hit,
            }
        )
        if raw_records is not None:
            _debug(
                raw_records,
                "MemWing readiness poll attempt",
                case_id=case_id,
                probe_id=probe_id,
                attempt_count=len(attempts),
                expected_source_event_count=len(expected_source_event_ids),
                retrieved_source_event_count=len(retrieved_source_event_ids),
                matched_source_event_ids=matched_source_event_ids,
                result_count=len(details.results),
                latency_ms=details.latency_ms,
                memory_search_error=search.error,
                durable_memory_available=hit,
            )
        last_details = details
        last_error = search.error
        if hit:
            return DurablePollResult(
                retrieved_contexts=details.contexts,
                search_error=search.error,
                retrieval_result=None,
                first_memory_available_at=attempted_at,
                durable_memory_available=True,
                extraction_timeout=False,
                attempts=attempts,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return DurablePollResult(
                retrieved_contexts=last_details.contexts,
                search_error=last_error,
                retrieval_result=None,
                first_memory_available_at=None,
                durable_memory_available=False,
                extraction_timeout=True,
                attempts=attempts,
            )
        sleep_seconds = min(poll_interval_seconds, remaining)
        if raw_records is not None:
            _debug(
                raw_records,
                "等待 MemWing readiness poll",
                case_id=case_id,
                probe_id=probe_id,
                seconds=round(sleep_seconds, 3),
                remaining_seconds=round(max(remaining, 0), 3),
            )
        time.sleep(sleep_seconds)


def _details_from_poll(poll: DurablePollResult) -> MemorySearchDetails:
    if not poll.attempts:
        return MemorySearchDetails(contexts=[], results=[], latency_ms=0, raw=None)
    last_raw = poll.attempts[-1]
    results = last_raw.get("memory_search_results")
    raw = last_raw.get("memory_search_raw")
    return MemorySearchDetails(
        contexts=poll.retrieved_contexts,
        results=results if isinstance(results, list) else [],
        latency_ms=_optional_int(last_raw.get("memory_search_latency_ms")) or 0,
        raw=raw if isinstance(raw, dict) else None,
    )


def _source_event_ids_from_results(results: list[dict[str, Any]]) -> list[str]:
    source_event_ids: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        raw_ids = result.get("source_event_ids")
        if isinstance(raw_ids, list):
            source_event_ids.extend(item for item in raw_ids if isinstance(item, str))
    return unique_preserve_order(source_event_ids)


def _run_write_live_batch(
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
    memory_poll_interval_seconds: float,
    memory_timeout_seconds: float,
) -> list[NormalizedResult]:
    _debug(raw_records, "检查 Feishu CLI 发送消息权限")
    feishu = FeishuCli(config.feishu.cli_bin)
    feishu.ensure_ready(required_scopes=_required_feishu_scopes(will_create_chat=False))
    workspace = Path(adapter.get_default_workspace()).expanduser()
    seed_chat_id = chats.seed_chat_id
    results: list[NormalizedResult] = []
    for case in cases:
        _debug(
            raw_records,
            "开始 write case",
            case_id=case.case_id,
            seed_chat_id=seed_chat_id,
            workspace=str(workspace),
        )
        before = _snapshot_memory_artifacts(workspace)
        seed_completed_at: str | None = None
        for message in case.seed_messages:
            _debug(
                raw_records,
                "发送 write seed 消息",
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
                    item_id=f"write_{message.id}",
                ),
            )
            raw_records["feishu"].append(
                {
                    "kind": "write_seed",
                    "case_id": case.case_id,
                    "seed_message_id": message.id,
                    "chat_id": seed_chat_id,
                    "result": sent_seed,
                }
            )
            seed_completed_at = utc_now_iso()
            if message_interval_seconds > 0:
                time.sleep(message_interval_seconds)
        if settle_seconds > 0:
            _debug(raw_records, "等待 write seed settle", case_id=case.case_id, seconds=settle_seconds)
            time.sleep(settle_seconds)
        poll_result = _poll_memory_artifact_change(
            workspace=workspace,
            before=before,
            poll_interval_seconds=memory_poll_interval_seconds,
            timeout_seconds=memory_timeout_seconds,
        )
        written_contexts = [
            change["added_text"]
            for change in poll_result.changed_files
            if isinstance(change.get("added_text"), str) and change["added_text"].strip()
        ]
        write_result = _evaluate_write(
            judge=judge,
            case_id=case.case_id,
            expected_memories=_expected_memories(case),
            noise_memories=_noise_memories(case),
            written_contexts=written_contexts,
        )
        raw_records.setdefault("memory_writes", []).append(
            {
                "case_id": case.case_id,
                "workspace": str(workspace),
                "before": _snapshot_raw(poll_result.before),
                "after": _snapshot_raw(poll_result.after),
                "changed_files": poll_result.changed_files,
                "first_changed_at": poll_result.first_changed_at,
                "timeout": poll_result.timeout,
                "write_judge": write_result.model_dump(mode="json") if write_result else None,
            }
        )
        results.append(
            _result_from_write(
                run_id=run_id,
                backend=backend,
                case=case,
                chat_id=seed_chat_id,
                seed_message_ids=[message.id for message in case.seed_messages],
                written_contexts=written_contexts,
                changed_files=poll_result.changed_files,
                seed_completed_at=seed_completed_at,
                first_changed_at=poll_result.first_changed_at,
                timeout=poll_result.timeout,
                write_result=write_result,
            )
        )
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return results


def _run_write_ingest_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    chats: LiveChatIds,
    raw_records: dict[str, Any],
    message_interval_seconds: float,
) -> list[NormalizedResult]:
    _debug(raw_records, "检查 Feishu CLI 发送消息权限")
    feishu = FeishuCli(config.feishu.cli_bin)
    feishu.ensure_ready(required_scopes=_required_feishu_scopes(will_create_chat=False))
    workspace = Path(adapter.get_default_workspace()).expanduser()
    chat_id = chats.seed_chat_id
    sent_by_case: dict[str, list[str]] = {case.case_id: [] for case in cases}
    completed_by_case: dict[str, str | None] = {case.case_id: None for case in cases}
    _debug(
        raw_records,
        "开始 write ingest batch",
        case_count=len(cases),
        chat_id=chat_id,
        workspace=str(workspace),
    )
    for case in cases:
        for message in case.seed_messages:
            _debug(
                raw_records,
                "发送 write ingest seed 消息",
                case_id=case.case_id,
                seed_message_id=message.id,
                chat_id=chat_id,
            )
            sent_seed = feishu.send_text(
                chat_id=chat_id,
                text=message.content,
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=f"ingest_{message.id}",
                ),
            )
            raw_records["feishu"].append(
                {
                    "kind": "write_ingest_seed",
                    "case_id": case.case_id,
                    "seed_message_id": message.id,
                    "chat_id": chat_id,
                    "result": sent_seed,
                }
            )
            sent_by_case[case.case_id].append(message.id)
            completed_by_case[case.case_id] = utc_now_iso()
            if message_interval_seconds > 0:
                time.sleep(message_interval_seconds)
    raw_records.setdefault("memory_writes", []).append(
        {
            "phase": "ingest",
            "workspace": str(workspace),
            "chat_id": chat_id,
            "case_ids": [case.case_id for case in cases],
            "sent_message_count": sum(len(ids) for ids in sent_by_case.values()),
            "note": "ingest phase only sends seed messages; run --mode write --phase evaluate later.",
        }
    )
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return [
        _result_from_write_ingest(
            run_id=run_id,
            backend=backend,
            case=case,
            chat_id=chat_id,
            seed_message_ids=sent_by_case[case.case_id],
            seed_completed_at=completed_by_case[case.case_id],
        )
        for case in cases
    ]


def _run_memwing_openclaw_plugin_write_ingest_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    openclaw_adapter: OpenClawNativeAdapter,
    memwing_adapter: MemWingAdapter,
    chats: LiveChatIds,
    raw_records: dict[str, Any],
    message_interval_seconds: float,
) -> list[NormalizedResult]:
    results = _run_write_ingest_batch(
        run_id=run_id,
        backend=backend,
        cases=cases,
        config=config,
        adapter=openclaw_adapter,
        chats=chats,
        raw_records=raw_records,
        message_interval_seconds=message_interval_seconds,
    )
    _require_openclaw_plugin_tool_evidence(
        config=config,
        adapter=openclaw_adapter,
        raw_records=raw_records,
    )
    for case in cases:
        poll = _poll_memwing_write_readiness(
            adapter=memwing_adapter,
            case=case,
            raw_records=raw_records,
            poll_interval_seconds=config.memwing.poll_interval_seconds,
            timeout_seconds=config.memwing.poll_timeout_seconds,
        )
        raw_records.setdefault("memwing_polls", []).append(
            {
                "mode": "memwing_openclaw_plugin_write_ingest",
                "case_id": case.case_id,
                **poll,
            }
        )
    _record_memwing_http_records(raw_records, memwing_adapter.records, openclaw_plugin=True)
    return results


def _poll_memwing_write_readiness(
    *,
    adapter: MemWingAdapter,
    case: BenchmarkCase,
    raw_records: dict[str, Any],
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    if poll_interval_seconds <= 0:
        raise BenchmarkError("memwing.poll_interval_seconds must be greater than 0")
    if timeout_seconds < 0:
        raise BenchmarkError("memwing.poll_timeout_seconds must be greater than or equal to 0")
    deadline = time.monotonic() + timeout_seconds
    attempts: list[dict[str, Any]] = []
    expected_items = list(case.expected_memory_items)
    if not expected_items:
        return {
            "attempts": attempts,
            "durable_memory_available": None,
            "extraction_timeout": False,
            "first_memory_available_at": None,
        }

    while True:
        attempted_at = utc_now_iso()
        searches: list[dict[str, Any]] = []
        matched_ids: list[str] = []
        for item in expected_items:
            search = _safe_memory_search(adapter, item.fact)
            search_raw = _memory_search_raw(search)
            hit = bool(search.details.contexts)
            if hit:
                matched_ids.append(item.id)
            row = {
                "mode": "memwing_openclaw_plugin_write_ingest",
                "case_id": case.case_id,
                "expected_memory_id": item.id,
                "query": item.fact,
                "durable_memory_available": hit,
                **search_raw,
            }
            searches.append(row)
            raw_records.setdefault("memory_searches", []).append(row)

        available = len(matched_ids) == len(expected_items)
        attempts.append(
            {
                "attempted_at": attempted_at,
                "matched_expected_memory_ids": matched_ids,
                "expected_memory_ids": [item.id for item in expected_items],
                "searches": searches,
                "durable_memory_available": available,
            }
        )
        _debug(
            raw_records,
            "MemWing write readiness poll attempt",
            case_id=case.case_id,
            attempt_count=len(attempts),
            matched_expected_memory_ids=matched_ids,
            expected_memory_count=len(expected_items),
            durable_memory_available=available,
        )
        if available:
            return {
                "attempts": attempts,
                "durable_memory_available": True,
                "extraction_timeout": False,
                "first_memory_available_at": attempted_at,
            }
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "attempts": attempts,
                "durable_memory_available": False,
                "extraction_timeout": True,
                "first_memory_available_at": None,
            }
        sleep_seconds = min(poll_interval_seconds, remaining)
        _debug(
            raw_records,
            "等待 MemWing write readiness poll",
            case_id=case.case_id,
            seconds=round(sleep_seconds, 3),
            remaining_seconds=round(max(remaining, 0), 3),
        )
        time.sleep(sleep_seconds)


def _run_write_evaluate_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: OpenClawNativeAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    chat_id: str | None,
) -> list[NormalizedResult]:
    workspace = Path(adapter.get_default_workspace()).expanduser()
    _debug(
        raw_records,
        "开始 write evaluate batch",
        case_count=len(cases),
        workspace=str(workspace),
    )
    snapshot = _snapshot_memory_artifacts(workspace)
    written_contexts = _memory_artifact_contexts(snapshot)
    evaluated_files = _snapshot_as_changed_files(snapshot)
    _debug(
        raw_records,
        "write evaluate workspace snapshot 完成",
        file_count=len(snapshot.files),
        non_empty_file_count=len(written_contexts),
        total_bytes=sum(len(text.encode("utf-8")) for text in snapshot.files.values()),
        evaluated_file_count=len(evaluated_files),
        files=[
            {
                "path": path,
                "bytes": len(text.encode("utf-8")),
                "lines": len(text.splitlines()),
            }
            for path, text in sorted(snapshot.files.items())
        ],
    )
    results: list[NormalizedResult] = []
    total_cases = len(cases)
    for index, case in enumerate(cases, start=1):
        expected_memories = _expected_memories(case)
        noise_memories = _noise_memories(case)
        allowed_other_memories = _expected_memories_for_other_cases(cases, case.case_id)
        _debug(
            raw_records,
            "write evaluate case 开始",
            case_id=case.case_id,
            case_index=index,
            case_count=total_cases,
            expected_memory_count=len(expected_memories),
            noise_memory_count=len(noise_memories),
            allowed_other_memory_count=len(allowed_other_memories),
            written_context_count=len(written_contexts),
            written_context_bytes=sum(
                len(context.encode("utf-8")) for context in written_contexts
            ),
        )
        judge_started = time.monotonic()
        _debug(raw_records, "write evaluate judge 开始", case_id=case.case_id)
        write_result = _evaluate_write(
            judge=judge,
            case_id=case.case_id,
            expected_memories=expected_memories,
            noise_memories=noise_memories,
            written_contexts=written_contexts,
            allowed_other_memories=allowed_other_memories,
        )
        _debug(
            raw_records,
            "write evaluate judge 完成",
            case_id=case.case_id,
            duration_ms=round((time.monotonic() - judge_started) * 1000),
            judge_available=write_result is not None,
            write_recall=write_result.write.write_recall if write_result else None,
            write_precision=write_result.write.write_precision if write_result else None,
        )
        raw_records.setdefault("memory_writes", []).append(
            {
                "phase": "evaluate",
                "case_id": case.case_id,
                "workspace": str(workspace),
                "snapshot": _snapshot_raw(snapshot),
                "evaluated_files": evaluated_files,
                "write_judge": write_result.model_dump(mode="json") if write_result else None,
            }
        )
        results.append(
            _result_from_write(
                run_id=run_id,
                backend=backend,
                case=case,
                chat_id=chat_id,
                seed_message_ids=[message.id for message in case.seed_messages],
                written_contexts=written_contexts,
                changed_files=evaluated_files,
                seed_completed_at=None,
                first_changed_at=snapshot.captured_at if written_contexts else None,
                timeout=False,
                write_result=write_result,
                phase="evaluate",
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
    feishu = FeishuCli(config.feishu.cli_bin)
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


def _poll_memory_artifact_change(
    *,
    workspace: Path,
    before: MemoryArtifactSnapshot,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> MemoryArtifactPollResult:
    deadline = time.monotonic() + timeout_seconds
    last_after = _snapshot_memory_artifacts(workspace)
    last_changed = _diff_memory_artifacts(before, last_after)
    while True:
        if last_changed:
            return MemoryArtifactPollResult(
                before=before,
                after=last_after,
                changed_files=last_changed,
                first_changed_at=last_after.captured_at,
                timeout=False,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return MemoryArtifactPollResult(
                before=before,
                after=last_after,
                changed_files=last_changed,
                first_changed_at=None,
                timeout=True,
            )
        time.sleep(min(poll_interval_seconds, remaining))
        last_after = _snapshot_memory_artifacts(workspace)
        last_changed = _diff_memory_artifacts(before, last_after)


def _snapshot_memory_artifacts(workspace: Path) -> MemoryArtifactSnapshot:
    files: dict[str, str] = {}
    candidates: list[Path] = []
    for name in ("MEMORY.md", "DREAMS.md"):
        candidates.append(workspace / name)
    memory_dir = workspace / "memory"
    if memory_dir.exists():
        candidates.extend(path for path in memory_dir.rglob("*.md") if path.is_file())
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        try:
            rel_path = path.relative_to(workspace).as_posix()
            files[rel_path] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return MemoryArtifactSnapshot(workspace=workspace, files=files, captured_at=utc_now_iso())


def _diff_memory_artifacts(
    before: MemoryArtifactSnapshot, after: MemoryArtifactSnapshot
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    paths = sorted(set(before.files) | set(after.files))
    for rel_path in paths:
        before_text = before.files.get(rel_path, "")
        after_text = after.files.get(rel_path, "")
        if before_text == after_text:
            continue
        added_lines = [
            line[2:]
            for line in ndiff(before_text.splitlines(), after_text.splitlines())
            if line.startswith("+ ")
        ]
        changed.append(
            {
                "path": rel_path,
                "before_bytes": len(before_text.encode("utf-8")),
                "after_bytes": len(after_text.encode("utf-8")),
                "added_line_count": len(added_lines),
                "added_text": "\n".join(added_lines),
            }
        )
    return changed


def _snapshot_raw(snapshot: MemoryArtifactSnapshot) -> dict[str, Any]:
    return {
        "workspace": str(snapshot.workspace),
        "captured_at": snapshot.captured_at,
        "files": {
            path: {"bytes": len(text.encode("utf-8")), "lines": len(text.splitlines())}
            for path, text in snapshot.files.items()
        },
    }


def _memory_artifact_contexts(snapshot: MemoryArtifactSnapshot) -> list[str]:
    contexts: list[str] = []
    for rel_path, text in sorted(snapshot.files.items()):
        stripped = text.strip()
        if not stripped:
            continue
        contexts.append(f"Source: {rel_path}\n{stripped}")
    return contexts


def _snapshot_as_changed_files(snapshot: MemoryArtifactSnapshot) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for rel_path, text in sorted(snapshot.files.items()):
        if not text.strip():
            continue
        files.append(
            {
                "path": rel_path,
                "before_bytes": 0,
                "after_bytes": len(text.encode("utf-8")),
                "added_line_count": len(text.splitlines()),
                "added_text": text,
                "source": "current_workspace_snapshot",
            }
        )
    return files


def _result_from_eval(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    probe,
    chat_id: str | None,
    seed_message_ids: list[str],
    answer: str,
    retrieved_contexts: list[str],
    retrieved_evidence_ids: list[str],
    actual_tool_evidence_ids: list[str],
    latency_ms: int | None,
    tokens: TokenUsage,
    memory_recall_latency_ms: int | None,
    retrieval_result: JudgeResult | None,
    answer_result: JudgeResult | None,
    raw: dict[str, Any],
) -> NormalizedResult:
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=probe.id,
        chat_id=chat_id,
        seed_chat_id=raw.get("seed_chat_id") if isinstance(raw.get("seed_chat_id"), str) else None,
        probe_chat_id=raw.get("probe_chat_id")
        if isinstance(raw.get("probe_chat_id"), str)
        else None,
        seed_message_ids=seed_message_ids,
        probe_message_id=_nested_str(raw, "probe_send_result", "message_id"),
        reply_message_id=_nested_str(raw, "reply", "message_id"),
        question=probe.question,
        answer=answer,
        expected_answer=probe.gold_answer,
        gold_evidence_ids=probe.gold_evidence_ids,
        retrieved_evidence_ids=retrieved_evidence_ids,
        retrieved_contexts=retrieved_contexts,
        retrieval_result_count=_optional_int(raw.get("memory_search_result_count")),
        retrieval_top_score=_optional_float(raw.get("memory_search_top_score")),
        retrieval_top_vector_score=_optional_float(raw.get("memory_search_top_vector_score")),
        retrieval_top_text_score=_optional_float(raw.get("memory_search_top_text_score")),
        retrieval_top_path=(
            raw.get("memory_search_top_path")
            if isinstance(raw.get("memory_search_top_path"), str)
            else None
        ),
        retrieval_top_start_line=_optional_int(raw.get("memory_search_top_start_line")),
        retrieval_top_end_line=_optional_int(raw.get("memory_search_top_end_line")),
        retrieval_source_mix=_int_dict(raw.get("memory_search_source_mix")),
        memory_search_warnings=_dict_list(raw.get("memory_search_warnings")),
        readiness_summary=raw.get("readiness") if isinstance(raw.get("readiness"), dict) else {},
        retrieval_recall_at_1=(
            retrieval_result.retrieval.recall_at_1 if retrieval_result else None
        ),
        retrieval_recall_at_3=(
            retrieval_result.retrieval.recall_at_3 if retrieval_result else None
        ),
        retrieval_recall_at_5=(
            retrieval_result.retrieval.recall_at_5 if retrieval_result else None
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
        answer_score=answer_result.answer.answer_score if answer_result else None,
        answer_correct=answer_result.answer.answer_correct if answer_result else None,
        temporal_correct=answer_result.answer.temporal_correct if answer_result else None,
        evidence_correct=answer_result.answer.evidence_correct if answer_result else None,
        noise_polluted=answer_result.answer.noise_polluted if answer_result else None,
        seed_completed_at=raw.get("seed_completed_at")
        if isinstance(raw.get("seed_completed_at"), str)
        else None,
        first_memory_available_at=(
            raw.get("first_memory_available_at")
            if isinstance(raw.get("first_memory_available_at"), str)
            else None
        ),
        durable_memory_available=(
            raw.get("durable_memory_available")
            if isinstance(raw.get("durable_memory_available"), bool)
            else None
        ),
        extraction_timeout=(
            raw.get("extraction_timeout")
            if isinstance(raw.get("extraction_timeout"), bool)
            else False
        ),
        probe_sent_at=raw.get("probe_sent_at")
        if isinstance(raw.get("probe_sent_at"), str)
        else None,
        answer_received_at=(
            raw.get("answer_received_at")
            if isinstance(raw.get("answer_received_at"), str)
            else None
        ),
        memory_search_latency_ms=_optional_int(raw.get("memory_search_latency_ms")),
        memory_availability_latency_ms=_latency_ms(
            raw.get("seed_completed_at"), raw.get("first_memory_available_at")
        )
        if isinstance(raw.get("seed_completed_at"), str)
        and isinstance(raw.get("first_memory_available_at"), str)
        else None,
        latency_ms=latency_ms,
        tokens=tokens,
        observability=Observability(
            memory_write_latency_ms=None,
            memory_availability_latency_ms=_latency_ms(
                raw.get("seed_completed_at"), raw.get("first_memory_available_at")
            )
            if isinstance(raw.get("seed_completed_at"), str)
            and isinstance(raw.get("first_memory_available_at"), str)
            else None,
            memory_write_tokens=None,
            memory_recall_latency_ms=memory_recall_latency_ms
            if memory_recall_latency_ms is not None
            else _optional_int(raw.get("memory_search_latency_ms")),
            memory_recall_tokens=None,
            answer_latency_ms=latency_ms,
            notes=[
                "OpenClaw native does not expose stable memory write latency/token usage.",
            ],
        ),
        raw={
            **raw,
            "retrieval_judge": retrieval_result.model_dump(mode="json")
            if retrieval_result
            else None,
            "answer_judge": answer_result.model_dump(mode="json") if answer_result else None,
        },
    )


def _result_from_write(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    chat_id: str | None,
    seed_message_ids: list[str],
    written_contexts: list[str],
    changed_files: list[dict[str, Any]],
    seed_completed_at: str | None,
    first_changed_at: str | None,
    timeout: bool,
    write_result: JudgeResult | None,
    phase: str = "full",
) -> NormalizedResult:
    expected_count = len(case.expected_memory_items)
    write = write_result.write if write_result else None
    matched_count = len(write.matched_expected_memory_ids) if write else None
    missing_count = (
        len(write.missing_expected_memory_ids)
        if write and write.missing_expected_memory_ids
        else (expected_count - matched_count if matched_count is not None else None)
    )
    unexpected_count = len(write.unexpected_facts) if write else None
    noise_count = len(write.noise_facts) if write else None
    wrong_count = len(write.wrong_facts) if write else None
    stale_count = len(write.stale_facts) if write else None
    memory_write_latency_ms = (
        _latency_ms(seed_completed_at, first_changed_at)
        if seed_completed_at and first_changed_at
        else None
    )
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=f"{case.case_id}_write",
        chat_id=chat_id,
        seed_chat_id=chat_id,
        seed_message_ids=seed_message_ids,
        question="memory_write",
        answer="",
        expected_answer="\n".join(item.fact for item in case.expected_memory_items),
        gold_evidence_ids=[item.id for item in case.expected_memory_items],
        retrieved_contexts=[],
        written_contexts=written_contexts,
        durable_memory_available=bool(changed_files),
        extraction_timeout=timeout,
        seed_completed_at=seed_completed_at,
        first_memory_available_at=first_changed_at,
        memory_write_latency_ms=memory_write_latency_ms,
        memory_availability_latency_ms=memory_write_latency_ms,
        write_expected_count=expected_count,
        write_matched_expected_count=matched_count,
        write_missing_expected_count=missing_count,
        write_unexpected_count=unexpected_count,
        write_noise_count=noise_count,
        write_wrong_count=wrong_count,
        write_stale_count=stale_count,
        write_changed_file_count=len(changed_files),
        write_written_claim_count=write.written_claim_count if write else None,
        write_recall=write.write_recall if write else None,
        write_precision=write.write_precision if write else None,
        tokens=TokenUsage(available=False, missing_reason="write mode does not collect tokens"),
        observability=Observability(
            memory_write_latency_ms=memory_write_latency_ms,
            memory_availability_latency_ms=memory_write_latency_ms,
            notes=[_write_observability_note(phase)],
        ),
        raw={
            "mode": "memory_write",
            "phase": phase,
            "seed_completed_at": seed_completed_at,
            "first_memory_available_at": first_changed_at,
            "durable_memory_available": bool(changed_files),
            "extraction_timeout": timeout,
            "changed_memory_files": changed_files,
            "write_judge": write_result.model_dump(mode="json") if write_result else None,
        },
    )


def _result_from_write_ingest(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    chat_id: str | None,
    seed_message_ids: list[str],
    seed_completed_at: str | None,
    raw_extra: dict[str, Any] | None = None,
    observability_note: str | None = None,
) -> NormalizedResult:
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=f"{case.case_id}_write_ingest",
        chat_id=chat_id,
        seed_chat_id=chat_id,
        probe_chat_id=chat_id,
        seed_message_ids=seed_message_ids,
        question="memory_write_ingest",
        answer="",
        expected_answer="\n".join(item.fact for item in case.expected_memory_items),
        gold_evidence_ids=[item.id for item in case.expected_memory_items],
        durable_memory_available=None,
        extraction_timeout=False,
        seed_completed_at=seed_completed_at,
        tokens=TokenUsage(available=False, missing_reason="write ingest does not collect tokens"),
        observability=Observability(
            notes=[
                observability_note
                or "Write ingest phase only sends seed messages; evaluate memory after OpenClaw finishes writing.",
            ],
        ),
        raw={
            "mode": "memory_write_ingest",
            "phase": "ingest",
            "seed_completed_at": seed_completed_at,
            **(raw_extra or {}),
        },
    )


def _result_from_memwing_write(
    *,
    run_id: str,
    backend: str,
    case: BenchmarkCase,
    seed_message_ids: list[str],
    written_contexts: list[str],
    search_latencies: list[int],
    search_errors: list[str],
    write_result: JudgeResult | None,
    searches: list[dict[str, Any]],
    readiness_summary: dict[str, Any] | None = None,
) -> NormalizedResult:
    expected_count = len(case.expected_memory_items)
    write = write_result.write if write_result else None
    matched_count = len(write.matched_expected_memory_ids) if write else None
    missing_count = (
        len(write.missing_expected_memory_ids)
        if write and write.missing_expected_memory_ids
        else (expected_count - matched_count if matched_count is not None else None)
    )
    unexpected_count = len(write.unexpected_facts) if write else None
    noise_count = len(write.noise_facts) if write else None
    wrong_count = len(write.wrong_facts) if write else None
    stale_count = len(write.stale_facts) if write else None
    memory_recall_latency_ms = sum(search_latencies) if search_latencies else None
    return NormalizedResult(
        run_id=run_id,
        backend=backend,
        case_id=case.case_id,
        probe_id=f"{case.case_id}_write",
        chat_id=None,
        seed_message_ids=seed_message_ids,
        question="memory_write",
        answer="",
        expected_answer="\n".join(item.fact for item in case.expected_memory_items),
        gold_evidence_ids=[item.id for item in case.expected_memory_items],
        written_contexts=written_contexts,
        durable_memory_available=bool(written_contexts),
        extraction_timeout=False,
        memory_search_latency_ms=memory_recall_latency_ms,
        write_expected_count=expected_count,
        write_matched_expected_count=matched_count,
        write_missing_expected_count=missing_count,
        write_unexpected_count=unexpected_count,
        write_noise_count=noise_count,
        write_wrong_count=wrong_count,
        write_stale_count=stale_count,
        write_changed_file_count=None,
        write_written_claim_count=write.written_claim_count if write else None,
        write_recall=write.write_recall if write else None,
        write_precision=write.write_precision if write else None,
        tokens=TokenUsage(available=False, missing_reason="write mode does not collect tokens"),
        observability=Observability(
            memory_recall_latency_ms=memory_recall_latency_ms,
            notes=[
                "MemWing write evaluate scores durable memory through HTTP search APIs.",
                MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
            ],
        ),
        readiness_summary=readiness_summary or {},
        raw={
            "mode": "memory_write",
            "phase": "evaluate",
            "backend": backend,
            "durable_memory_available": bool(written_contexts),
            "extraction_timeout": False,
            "changed_memory_files": None,
            "changed_file_metrics_available": False,
            "changed_file_metrics_missing_reason": MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
            "memory_searches": searches,
            "memory_search_errors": search_errors,
            "readiness_unavailable": readiness_summary,
            "write_judge": write_result.model_dump(mode="json") if write_result else None,
        },
    )


def _write_observability_note(phase: str) -> str:
    if phase == "evaluate":
        return "Write evaluate phase scores current durable memory files without sending Feishu messages."
    return "Write mode evaluates durable memory file diffs without forced flush."


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


def _evaluate_retrieval(
    *,
    judge: LlmJudge | None,
    case: BenchmarkCase,
    probe: Probe,
    retrieved_contexts: list[str],
) -> JudgeResult | None:
    if judge is None:
        return None
    return judge.evaluate_retrieval(
        case_id=case.case_id,
        probe=probe,
        gold_memories=_gold_memories(case, probe.gold_evidence_ids),
        old_memories=_gold_memories(case, probe.old_evidence_ids),
        retrieved_context=retrieved_contexts,
    )


def _retrieval_hit(result: JudgeResult | None) -> bool:
    if result is None:
        return False
    retrieval = result.retrieval
    return bool(retrieval.recall_at_1 or retrieval.recall_at_3 or retrieval.recall_at_5)


def _evaluate_answer(
    *,
    judge: LlmJudge | None,
    case: BenchmarkCase,
    probe: Probe,
    answer: str,
    retrieved_contexts: list[str],
) -> JudgeResult | None:
    if judge is None:
        return None
    return judge.evaluate_answer(
        case_id=case.case_id,
        probe=probe,
        gold_memories=_gold_memories(case, probe.gold_evidence_ids),
        old_memories=_gold_memories(case, probe.old_evidence_ids),
        retrieved_context=retrieved_contexts,
        answer=answer,
    )


def _evaluate_write(
    *,
    judge: LlmJudge | None,
    case_id: str,
    expected_memories: list[GoldMemory],
    noise_memories: list[GoldMemory],
    written_contexts: list[str],
    allowed_other_memories: list[GoldMemory] | None = None,
) -> JudgeResult | None:
    if judge is None:
        return None
    return judge.evaluate_write(
        case_id=case_id,
        expected_memories=expected_memories,
        noise_memories=noise_memories,
        written_context=written_contexts,
        allowed_other_memories=allowed_other_memories,
    )


def _gold_memories(case: BenchmarkCase, memory_ids: list[str]) -> list[GoldMemory]:
    by_id = {
        message.id: GoldMemory(id=message.id, time=message.time, fact=message.content)
        for message in case.seed_messages
    }
    for item in case.expected_memory_items:
        by_id.setdefault(item.id, GoldMemory(id=item.id, time=None, fact=item.fact))
    return [by_id[memory_id] for memory_id in memory_ids if memory_id in by_id]


def _expected_memories(case: BenchmarkCase) -> list[GoldMemory]:
    return [
        GoldMemory(id=item.id, time=None, fact=item.fact) for item in case.expected_memory_items
    ]


def _expected_memories_for_other_cases(
    cases: list[BenchmarkCase], current_case_id: str
) -> list[GoldMemory]:
    return [
        GoldMemory(id=item.id, time=None, fact=item.fact)
        for case in cases
        if case.case_id != current_case_id
        for item in case.expected_memory_items
    ]


def _noise_memories(case: BenchmarkCase) -> list[GoldMemory]:
    return [
        GoldMemory(id=message.id, time=message.time, fact=message.content)
        for message in case.seed_messages
        if not message.should_write_memory
    ]


def _safe_memory_search(adapter: Any, question: str) -> MemorySearchOutcome:
    try:
        return MemorySearchOutcome(details=adapter.memory_search_details(question, max_results=5))
    except Exception as exc:
        return MemorySearchOutcome(
            details=MemorySearchDetails(contexts=[], results=[], latency_ms=0, raw=None),
            error=str(exc),
        )


def _memory_search_raw(search: MemorySearchOutcome) -> dict[str, Any]:
    top = search.details.results[0] if search.details.results else {}
    raw_warnings = search.details.raw.get("warnings") if search.details.raw else None
    return {
        "memory_search_error": search.error,
        "memory_search_latency_ms": search.details.latency_ms,
        "memory_search_result_count": len(search.details.results),
        "memory_search_results": search.details.results,
        "memory_search_raw": search.details.raw,
        "memory_search_source_mix": _source_mix(search.details.results),
        "memory_search_warnings": raw_warnings if isinstance(raw_warnings, list) else [],
        "memory_search_top_score": top.get("score") if isinstance(top, dict) else None,
        "memory_search_top_vector_score": top.get("vectorScore") if isinstance(top, dict) else None,
        "memory_search_top_text_score": top.get("textScore") if isinstance(top, dict) else None,
        "memory_search_top_path": top.get("path") if isinstance(top, dict) else None,
        "memory_search_top_start_line": top.get("startLine") if isinstance(top, dict) else None,
        "memory_search_top_end_line": top.get("endLine") if isinstance(top, dict) else None,
    }


def _source_mix(results: list[dict[str, Any]]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for result in results:
        source = result.get("source")
        if not isinstance(source, str) or not source:
            source = "unknown"
        mix[source] = mix.get(source, 0) + 1
    return mix


def _int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, int)
    }


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _confirm_side_effect(description: str, yes: bool) -> None:
    if yes:
        return
    confirmed = typer.confirm(f"将执行外部副作用：{description}。是否继续？")
    if not confirmed:
        raise BenchmarkError(f"用户取消：{description}")


def _debug(raw_records: dict[str, Any], message: str, **fields: Any) -> None:
    record = {"at": utc_now_iso(), "message": message, **fields}
    raw_records.setdefault("debug", []).append(record)
    suffix = ""
    if fields:
        suffix = " " + " ".join(f"{key}={value!r}" for key, value in fields.items())
    typer.echo(f"[debug] {message}{suffix}", err=True)


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
