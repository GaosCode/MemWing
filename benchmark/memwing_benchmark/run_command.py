from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from memwing_benchmark.adapters.memwing import MemWingAdapter
from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.config import (
    apply_overrides,
    load_config,
    sanitize_config_for_run,
    validate_config_for_backend,
)
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluation import _build_judge
from memwing_benchmark.live_workspace import (
    LiveChatIds,
    LiveWorkspaceRestore,
    prepare_live_chat as _prepare_live_chat,
    prepare_live_workspace as _prepare_live_workspace,
    prepare_write_ingest_chat as _prepare_write_ingest_chat,
    restore_live_workspace as _restore_live_workspace,
)
from memwing_benchmark.memwing_retrieval import (
    _run_memwing_retrieval_batch,
)
from memwing_benchmark.memwing_write import (
    _run_memwing_openclaw_plugin_write_ingest_batch,
    _run_memwing_write_evaluate_batch,
    _run_memwing_write_ingest_batch,
)
from memwing_benchmark.openclaw_native_runs import (
    _run_live,
    _run_offline,
    _run_offline_batch,
    _run_write_evaluate_batch,
    _run_write_ingest_batch,
    _run_write_live_batch,
)
from memwing_benchmark.report import write_run_outputs
from memwing_benchmark.run_records import (
    _empty_raw_records,
    _memwing_pipeline_run_config,
    _record_memwing_http_records,
    _run_mode_name,
)
from memwing_benchmark.schema import load_cases, make_run_id, utc_now_iso
from memwing_benchmark.run_command_support import (
    MEMWING_HTTP_BACKEND,
    MEMWING_OPENCLAW_PLUGIN_BACKEND,
    _preflight_memwing_http,
    _preflight_memwing_openclaw_plugin,
    _validate_run_options,
    _with_memwing_write_evaluate_pipeline_timeout,
)




def run(
    *,
    config_path: Path,
    backend: str,
    mode: str,
    phase: str,
    ingest_run_id: str | None,
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
    preseed_expected: bool,
    preseed_graph_mode: str,
) -> Path:
    backend, ingest_run_id = _validate_run_options(
        backend=backend,
        mode=mode,
        phase=phase,
        ingest_run_id=ingest_run_id,
        live=live,
        batch=batch,
        memory_poll_interval_seconds=memory_poll_interval_seconds,
        memory_timeout_seconds=memory_timeout_seconds,
        pg_preseed_per_case=pg_preseed_per_case,
        preseed_expected=preseed_expected,
        preseed_graph_mode=preseed_graph_mode,
    )
    config = apply_overrides(
        load_config(config_path),
        runs_dir=runs_dir,
        chat_id=chat_id,
        trajectory_dir=trajectory_dir,
    )
    config = _with_memwing_write_evaluate_pipeline_timeout(
        config,
        backend=backend,
        mode=mode,
        phase=phase,
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

    raw_records: dict[str, Any] = _empty_raw_records()
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
                preseed_expected=preseed_expected,
                preseed_graph_mode=preseed_graph_mode,
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
                runs_root=Path(config.paths.runs_dir).expanduser(),
                ingest_run_id=ingest_run_id,
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
            "preseed_expected": preseed_expected,
            "preseed_graph_mode": preseed_graph_mode if preseed_expected else None,
            "requested_ingest_run_id": ingest_run_id,
            **_memwing_pipeline_run_config(
                pg_preseed_per_case=pg_preseed_per_case,
                preseed_expected=preseed_expected,
            ),
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
                preseed_expected=preseed_expected,
                preseed_graph_mode=preseed_graph_mode,
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
                "preseed_expected": preseed_expected,
                "preseed_graph_mode": preseed_graph_mode if preseed_expected else None,
                **_memwing_pipeline_run_config(
                    pg_preseed_per_case=pg_preseed_per_case,
                    preseed_expected=preseed_expected,
                ),
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
                runs_root=Path(config.paths.runs_dir).expanduser(),
                ingest_run_id=ingest_run_id,
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
                "requested_ingest_run_id": ingest_run_id,
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
