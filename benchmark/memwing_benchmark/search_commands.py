from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from memwing_benchmark.adapters.memwing import (
    MemWingAdapter,
    MemWingCaseScope,
    memwing_case_scope,
)
from memwing_benchmark.adapters.openclaw_native import MemorySearchDetails
from memwing_benchmark.config import load_config, validate_config_for_backend
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.json_utils import dumps_json
from memwing_benchmark.schema import load_cases


MEMWING_HTTP_BACKEND = "memwing-http"


def register_search_commands(app: typer.Typer) -> None:
    @app.command("search")
    def search_command(
        query: str = typer.Argument(..., help="检索 query。"),
        config_path: Path = typer.Option(Path("config.example.json"), "--config"),
        limit: int = typer.Option(10, "--limit", "-k"),
        mode: str = typer.Option("current", "--mode"),
        run_id: str | None = typer.Option(None, "--run-id"),
        case_id: str | None = typer.Option(None, "--case-id"),
        project_memory_space_id: str | None = typer.Option(None, "--project-memory-space-id"),
        group_id: str | None = typer.Option(None, "--group-id"),
        thread_id: str | None = typer.Option(None, "--thread-id"),
        shared_group_id: str | None = typer.Option(None, "--shared-group-id"),
        health_check: bool = typer.Option(True, "--health/--no-health"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """直接调用 MemWing HTTP search-memory，打印 top-k 结果。"""

        try:
            run_memwing_search_command(
                config_path=config_path,
                query=query,
                limit=limit,
                mode=mode,
                run_id=run_id,
                case_id=case_id,
                project_memory_space_id=project_memory_space_id,
                group_id=group_id,
                thread_id=thread_id,
                shared_group_id=shared_group_id,
                health_check=health_check,
                json_output=json_output,
            )
        except BenchmarkError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc

    @app.command("search-case")
    def search_case_command(
        config_path: Path = typer.Option(Path("config.example.json"), "--config"),
        cases_path: Path = typer.Option(Path("datasets"), "--cases"),
        case_id: str = typer.Option(..., "--case-id"),
        run_id: str | None = typer.Option(None, "--run-id"),
        limit: int = typer.Option(10, "--limit", "-k"),
        mode: str = typer.Option("current", "--mode"),
        project_memory_space_id: str | None = typer.Option(None, "--project-memory-space-id"),
        group_id: str | None = typer.Option(None, "--group-id"),
        thread_id: str | None = typer.Option(None, "--thread-id"),
        shared_group_id: str | None = typer.Option(None, "--shared-group-id"),
        health_check: bool = typer.Option(True, "--health/--no-health"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """按数据集 case 的 probes 逐条检索，打印每个 probe 的 top-k。"""

        try:
            run_memwing_search_case_command(
                config_path=config_path,
                cases_path=cases_path,
                case_id=case_id,
                run_id=run_id,
                limit=limit,
                mode=mode,
                project_memory_space_id=project_memory_space_id,
                group_id=group_id,
                thread_id=thread_id,
                shared_group_id=shared_group_id,
                health_check=health_check,
                json_output=json_output,
            )
        except BenchmarkError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc


def run_memwing_search_command(
    *,
    config_path: Path,
    query: str,
    limit: int,
    mode: str,
    run_id: str | None,
    case_id: str | None,
    project_memory_space_id: str | None,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
    health_check: bool,
    json_output: bool,
) -> None:
    config = load_config(config_path)
    validate_config_for_backend(config, backend=MEMWING_HTTP_BACKEND)
    scope = _memwing_search_scope(
        config=config,
        run_id=run_id,
        case_id=case_id,
        project_memory_space_id=project_memory_space_id,
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
    )
    adapter = MemWingAdapter(config.memwing)
    if health_check:
        adapter.health()
    details = adapter.memory_search_details(
        query,
        limit=limit,
        scope=scope,
        mode=mode,
    )
    _emit_memwing_search_result(
        query=query,
        mode=mode,
        scope=scope,
        details=details,
        json_output=json_output,
    )


def run_memwing_search_case_command(
    *,
    config_path: Path,
    cases_path: Path,
    case_id: str,
    run_id: str | None,
    limit: int,
    mode: str,
    project_memory_space_id: str | None,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
    health_check: bool,
    json_output: bool,
) -> None:
    config = load_config(config_path)
    validate_config_for_backend(config, backend=MEMWING_HTTP_BACKEND)
    case = load_cases(cases_path, case_id=case_id)[0]
    scope = _memwing_search_scope(
        config=config,
        run_id=run_id,
        case_id=case.case_id if run_id is not None else None,
        project_memory_space_id=project_memory_space_id,
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
    )
    adapter = MemWingAdapter(config.memwing)
    if health_check:
        adapter.health()
    records: list[dict[str, Any]] = []
    for probe in case.probes:
        details = adapter.memory_search_details(
            probe.question,
            limit=limit,
            scope=scope,
            mode=mode,
        )
        records.append(
            {
                "case_id": case.case_id,
                "probe_id": probe.id,
                "query": probe.question,
                "mode": mode,
                "scope": scope.payload() if scope is not None else None,
                "latency_ms": details.latency_ms,
                "contexts": details.contexts,
                "results": details.results,
                "raw": details.raw,
            }
        )
    if json_output:
        typer.echo(dumps_json({"case_id": case.case_id, "probes": records}))
        return
    typer.echo(
        f"case={case.case_id} probes={len(records)} mode={mode} "
        f"scope={_scope_label(scope)} limit={limit}"
    )
    for record in records:
        typer.echo("")
        typer.echo(f"{record['case_id']}/{record['probe_id']}: {record['query']}")
        _print_search_hits(record["results"], latency_ms=record["latency_ms"])


def _memwing_search_scope(
    *,
    config,
    run_id: str | None,
    case_id: str | None,
    project_memory_space_id: str | None,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
) -> MemWingCaseScope | None:
    normalized_run_id = _optional_cli_text(run_id, "--run-id")
    normalized_case_id = _optional_cli_text(case_id, "--case-id")
    explicit_scope = {
        "project_memory_space_id": _optional_cli_text(
            project_memory_space_id,
            "--project-memory-space-id",
        ),
        "group_id": _optional_cli_text(group_id, "--group-id"),
        "thread_id": _optional_cli_text(thread_id, "--thread-id"),
        "shared_group_id": _optional_cli_text(shared_group_id, "--shared-group-id"),
    }
    has_benchmark_scope = normalized_run_id is not None or normalized_case_id is not None
    has_explicit_scope = any(value is not None for value in explicit_scope.values())
    if has_benchmark_scope and has_explicit_scope:
        raise BenchmarkError("--run-id/--case-id cannot be combined with explicit scope options")
    if has_benchmark_scope:
        if normalized_run_id is None or normalized_case_id is None:
            raise BenchmarkError("--run-id and --case-id must be provided together")
        return memwing_case_scope(
            config=config.memwing,
            run_id=normalized_run_id,
            case_id=normalized_case_id,
        )
    if not has_explicit_scope:
        return None
    return MemWingCaseScope(
        project_memory_space_id=explicit_scope["project_memory_space_id"]
        or config.memwing.project_memory_space_id,
        group_id=explicit_scope["group_id"] or config.memwing.group_id,
        thread_id=explicit_scope["thread_id"] or config.memwing.thread_id,
        shared_group_id=explicit_scope["shared_group_id"] or config.memwing.shared_group_id or None,
    )


def _optional_cli_text(value: str | None, option_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise BenchmarkError(f"{option_name} must not be empty")
    return normalized


def _emit_memwing_search_result(
    *,
    query: str,
    mode: str,
    scope: MemWingCaseScope | None,
    details: MemorySearchDetails,
    json_output: bool,
) -> None:
    if json_output:
        typer.echo(
            dumps_json(
                {
                    "query": query,
                    "mode": mode,
                    "scope": scope.payload() if scope is not None else None,
                    "latency_ms": details.latency_ms,
                    "contexts": details.contexts,
                    "results": details.results,
                    "raw": details.raw,
                }
            )
        )
        return
    typer.echo(
        f"query={query} mode={mode} scope={_scope_label(scope)} "
        f"hits={len(details.results)} latency_ms={details.latency_ms}"
    )
    _print_search_hits(details.results, latency_ms=details.latency_ms)


def _print_search_hits(results: list[dict[str, Any]], *, latency_ms: int) -> None:
    if not results:
        typer.echo(f"no hits latency_ms={latency_ms}")
        return
    for result in results:
        rank = result.get("rank")
        source = result.get("source") or "unknown"
        score = result.get("score")
        item_id = result.get("id") or "-"
        memory_ids = ",".join(result.get("memory_item_ids") or [])
        source_ids = ",".join(result.get("source_event_ids") or [])
        typer.echo(
            f"{rank}. source={source} score={_cli_value(score)} id={item_id} "
            f"memory_ids={memory_ids or '-'} source_event_ids={source_ids or '-'}"
        )
        typer.echo(f"   {_one_line(result.get('snippet'))}")


def _scope_label(scope: MemWingCaseScope | None) -> str:
    if scope is None:
        return "config-default"
    return (
        f"{scope.project_memory_space_id}/"
        f"{scope.group_id}/"
        f"{scope.thread_id}"
    )


def _one_line(value: object, *, max_chars: int = 180) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 3]}..."


def _cli_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)
