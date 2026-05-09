from __future__ import annotations

from pathlib import Path

import typer

from memwing_benchmark.adapters.memwing import MemWingAdapter
from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.channels.feishu_cli import FeishuCli
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.live_workspace import (
    LiveChatIds,
    LiveWorkspaceRestore,
    prepare_live_chat as _prepare_live_chat,
    prepare_live_workspace as _prepare_live_workspace,
    prepare_write_ingest_chat as _prepare_write_ingest_chat,
    restore_live_workspace as _restore_live_workspace,
)
from memwing_benchmark.evaluation import (
    DurablePollResult,
    MEMWING_CHANGED_FILE_METRICS_MISSING_REASON,
    MemorySearchOutcome,
    _build_judge,
    _evaluate_answer,
    _evaluate_retrieval,
    _evaluate_write,
    _expected_memories,
    _expected_memories_for_other_cases,
    _gold_memories,
    _memory_search_raw,
    _memwing_write_scored_contexts,
    _noise_memories,
    _result_from_eval,
    _result_from_memwing_write,
    _result_from_write,
    _result_from_write_ingest,
    _retrieval_hit,
    _safe_memory_search,
    _source_mix,
    _write_quality_ratios,
)
from memwing_benchmark.memwing_retrieval import (
    MEMWING_REAL_SEARCH_MAX_RESULTS,
    _details_from_poll,
    _poll_memwing_readiness,
    _require_memwing_real_search_components,
    _run_memwing_expected_preseed_retrieval_batch,
    _run_memwing_expected_preseed_retrieval_case,
    _run_memwing_preseeded_retrieval_batch,
    _run_memwing_real_ingest_retrieval_batch,
    _run_memwing_real_ingest_retrieval_case,
    _run_memwing_retrieval_batch,
    _run_memwing_retrieval_case,
    _source_event_ids_from_results,
)
from memwing_benchmark.memwing_write import (
    MemWingWriteIngestRecord,
    _await_memwing_write_evaluate_readiness,
    _load_memwing_write_ingest_records,
    _poll_memwing_write_readiness,
    _run_memwing_openclaw_plugin_write_ingest_batch,
    _run_memwing_write_evaluate_batch,
    _run_memwing_write_ingest_batch,
)
from memwing_benchmark.openclaw_native_runs import (
    MemoryArtifactPollResult,
    MemoryArtifactSnapshot,
    _diff_memory_artifacts,
    _memory_artifact_contexts,
    _message_text,
    _poll_durable_memory,
    _poll_memory_artifact_change,
    _require_openclaw_plugin_tool_evidence,
    _run_live,
    _run_offline,
    _run_offline_batch,
    _run_write_evaluate_batch,
    _run_write_ingest_batch,
    _run_write_live_batch,
    _snapshot_as_changed_files,
    _snapshot_memory_artifacts,
    _snapshot_raw,
    make_idempotency_key,
)
from memwing_benchmark.run_records import (
    MEMWING_FULL_DERIVED_READINESS_PROFILE,
    _current_truth_branch_timings,
    _dict_list,
    _empty_raw_records,
    _int_dict,
    _latency_ms,
    _memwing_pipeline_run_config,
    _nested_str,
    _optional_float,
    _optional_int,
    _read_json_object,
    _record_memwing_http_records,
    _run_mode_name,
    _text_list_from_mapping,
)
from memwing_benchmark import evaluate_preseeded_command as _evaluate_preseeded_command
from memwing_benchmark import run_command as _run_command
from memwing_benchmark.search_commands import register_search_commands


__all__ = [
    "DurablePollResult",
    "FeishuCli",
    "LiveChatIds",
    "LiveWorkspaceRestore",
    "MEMWING_CHANGED_FILE_METRICS_MISSING_REASON",
    "MEMWING_FULL_DERIVED_READINESS_PROFILE",
    "MEMWING_REAL_SEARCH_MAX_RESULTS",
    "MemWingWriteIngestRecord",
    "MemoryArtifactPollResult",
    "MemoryArtifactSnapshot",
    "MemorySearchOutcome",
    "MemWingAdapter",
    "OpenClawNativeAdapter",
    "_await_memwing_write_evaluate_readiness",
    "_build_judge",
    "_current_truth_branch_timings",
    "_details_from_poll",
    "_dict_list",
    "_diff_memory_artifacts",
    "_empty_raw_records",
    "_evaluate_answer",
    "_evaluate_retrieval",
    "_evaluate_write",
    "_expected_memories",
    "_expected_memories_for_other_cases",
    "_gold_memories",
    "_int_dict",
    "_latency_ms",
    "_load_memwing_write_ingest_records",
    "_memwing_pipeline_run_config",
    "_memwing_write_scored_contexts",
    "_memory_artifact_contexts",
    "_memory_search_raw",
    "_message_text",
    "_nested_str",
    "_noise_memories",
    "_optional_float",
    "_optional_int",
    "_poll_durable_memory",
    "_poll_memwing_readiness",
    "_poll_memwing_write_readiness",
    "_poll_memory_artifact_change",
    "_prepare_live_chat",
    "_prepare_live_workspace",
    "_prepare_write_ingest_chat",
    "_read_json_object",
    "_record_memwing_http_records",
    "_require_memwing_real_search_components",
    "_require_openclaw_plugin_tool_evidence",
    "_restore_live_workspace",
    "_result_from_eval",
    "_result_from_memwing_write",
    "_result_from_write",
    "_result_from_write_ingest",
    "_retrieval_hit",
    "_run_live",
    "_run_memwing_expected_preseed_retrieval_batch",
    "_run_memwing_expected_preseed_retrieval_case",
    "_run_memwing_openclaw_plugin_write_ingest_batch",
    "_run_memwing_preseeded_retrieval_batch",
    "_run_memwing_real_ingest_retrieval_batch",
    "_run_memwing_real_ingest_retrieval_case",
    "_run_memwing_retrieval_batch",
    "_run_memwing_retrieval_case",
    "_run_memwing_write_evaluate_batch",
    "_run_memwing_write_ingest_batch",
    "_run_mode_name",
    "_run_offline",
    "_run_offline_batch",
    "_run_write_evaluate_batch",
    "_run_write_ingest_batch",
    "_run_write_live_batch",
    "_safe_memory_search",
    "_snapshot_as_changed_files",
    "_snapshot_memory_artifacts",
    "_snapshot_raw",
    "_source_event_ids_from_results",
    "_source_mix",
    "_text_list_from_mapping",
    "_write_quality_ratios",
    "app",
    "make_idempotency_key",
]

app = typer.Typer(add_completion=False, invoke_without_command=True)
register_search_commands(app)


def _sync_run_command_dependencies() -> None:
    _run_command.MemWingAdapter = MemWingAdapter
    _run_command.OpenClawNativeAdapter = OpenClawNativeAdapter
    _run_command._build_judge = _build_judge
    _evaluate_preseeded_command.MemWingAdapter = MemWingAdapter
    _evaluate_preseeded_command._build_judge = _build_judge


@app.command("evaluate-preseeded")
def evaluate_preseeded_command(
    config_path: Path = typer.Option(Path("config.example.json"), "--config"),
    cases_path: Path = typer.Option(Path("datasets"), "--cases"),
    run_id: str = typer.Option(..., "--run-id"),
    case_id: str | None = typer.Option(None, "--case-id"),
    batch: bool = typer.Option(False, "--batch"),
    limit: int = typer.Option(MEMWING_REAL_SEARCH_MAX_RESULTS, "--limit", "-k"),
    runs_dir: Path | None = typer.Option(None, "--runs-dir"),
    health_check: bool = typer.Option(True, "--health/--no-health"),
) -> None:
    """评测已经植入的 MemWing benchmark scope，不重新写入记忆。"""

    try:
        run_dir = _run_memwing_preseeded_evaluate_command(
            config_path=config_path,
            cases_path=cases_path,
            source_run_id=run_id,
            case_id=case_id,
            batch=batch,
            limit=limit,
            runs_dir=runs_dir,
            health_check=health_check,
        )
        typer.echo(str(run_dir))
    except BenchmarkError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config_path: Path = typer.Option(Path("config.example.json"), "--config"),
    backend: str = typer.Option("openclaw-native", "--backend"),
    mode: str = typer.Option("retrieval", "--mode"),
    phase: str = typer.Option("full", "--phase"),
    ingest_run_id: str | None = typer.Option(None, "--ingest-run-id"),
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
    preseed_expected: bool = typer.Option(False, "--preseed-expected"),
    preseed_graph_mode: str = typer.Option("direct_neo4j", "--preseed-graph-mode"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    try:
        run(
            config_path=config_path,
            backend=backend,
            mode=mode,
            phase=phase,
            ingest_run_id=ingest_run_id,
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
            preseed_expected=preseed_expected,
            preseed_graph_mode=preseed_graph_mode,
        )
    except BenchmarkError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


def _run_memwing_preseeded_evaluate_command(**kwargs):
    _sync_run_command_dependencies()
    return _evaluate_preseeded_command._run_memwing_preseeded_evaluate_command(**kwargs)


def run(**kwargs):
    _sync_run_command_dependencies()
    return _run_command.run(**kwargs)
