from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
import subprocess
from typing import Literal

import typer

from memwing_benchmark.config import BenchmarkConfig, load_config
from memwing_benchmark.schema import BenchmarkCase, ExpectedMemoryItem, Probe, SeedMessage, load_cases


app = typer.Typer(add_completion=False, invoke_without_command=True)

Action = Literal["replace", "seed", "cleanup"]
SEED_MARKER = "memwing_benchmark_pg_seed"


@app.callback(invoke_without_command=True)
def main(
    config_path: Path = typer.Option(Path("config.local.json"), "--config"),
    cases_path: Path = typer.Option(Path("datasets"), "--cases"),
    case_id: str | None = typer.Option(None, "--case-id"),
    action: Action = typer.Option("replace", "--action"),
    cleanup_all_benchmark_cases: bool = typer.Option(True, "--cleanup-all-benchmark-cases/--case-only"),
    database_url: str | None = typer.Option(None, "--database-url", envvar="DATABASE_URL"),
    print_sql: bool = typer.Option(False, "--print-sql"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    config = load_config(config_path)
    target_cases = load_cases(cases_path, case_id=case_id)
    cleanup_cases = load_cases(cases_path) if cleanup_all_benchmark_cases else target_cases
    sql = build_pg_seed_sql(
        config=config,
        target_cases=target_cases,
        cleanup_cases=cleanup_cases,
        action=action,
    )
    if print_sql:
        typer.echo(sql)
        return
    if action in {"replace", "cleanup"} and not yes:
        raise typer.BadParameter("cleanup actions require --yes")
    run_pg_seed(
        config=config,
        target_cases=target_cases,
        cleanup_cases=cleanup_cases,
        action=action,
        database_url=database_url,
    )
    target_ids = ", ".join(case.case_id for case in target_cases)
    typer.echo(f"{action} completed for {target_ids}")


def build_pg_seed_sql(
    *,
    config: BenchmarkConfig,
    target_cases: list[BenchmarkCase],
    cleanup_cases: list[BenchmarkCase],
    action: Action,
) -> str:
    statements = ["BEGIN;"]
    if action in {"replace", "cleanup"}:
        statements.extend(_cleanup_sql(cleanup_cases))
    if action in {"replace", "seed"}:
        statements.extend(_scope_sql(config))
        for case in target_cases:
            statements.extend(_source_event_sql(config, case))
            statements.extend(_memory_item_sql(config, case))
    statements.append("COMMIT;")
    return "\n\n".join(statements)


def run_pg_seed(
    *,
    config: BenchmarkConfig,
    target_cases: list[BenchmarkCase],
    cleanup_cases: list[BenchmarkCase],
    action: Action,
    database_url: str | None = None,
) -> dict[str, object]:
    sql = build_pg_seed_sql(
        config=config,
        target_cases=target_cases,
        cleanup_cases=cleanup_cases,
        action=action,
    )
    _run_psql(sql, database_url=database_url)
    return {
        "action": action,
        "target_case_ids": [case.case_id for case in target_cases],
        "cleanup_case_ids": [case.case_id for case in cleanup_cases],
        "target_source_event_count": sum(len(case.seed_messages) for case in target_cases),
        "target_memory_item_count": sum(len(case.expected_memory_items) for case in target_cases),
        "cleanup_source_event_count": sum(len(case.seed_messages) for case in cleanup_cases),
        "cleanup_memory_item_count": sum(len(case.expected_memory_items) for case in cleanup_cases),
        "runner": "database_url" if database_url else "docker_compose_postgres",
    }


def _cleanup_sql(cases: list[BenchmarkCase]) -> list[str]:
    source_ids = _case_source_ids(cases)
    memory_ids = _case_memory_ids(cases)
    source_array = _text_array(source_ids)
    memory_array = _text_array(memory_ids)
    return [
        f"DELETE FROM memory_recall_events WHERE memory_id = ANY({memory_array});",
        f"DELETE FROM memory_versions WHERE memory_id = ANY({memory_array});",
        (
            "DELETE FROM memory_graph_links "
            f"WHERE memory_id = ANY({memory_array}) OR source_event_id = ANY({source_array});"
        ),
        (
            "DELETE FROM graph_write_jobs "
            f"WHERE memory_id = ANY({memory_array}) OR source_event_ids && {source_array};"
        ),
        f"DELETE FROM forgetting_review_candidates WHERE memory_id = ANY({memory_array});",
        (
            "DELETE FROM push_candidates "
            f"WHERE memory_item_ids && {memory_array} OR source_event_ids && {source_array};"
        ),
        f"DELETE FROM memory_items WHERE id = ANY({memory_array});",
        f"DELETE FROM evidence_chunks WHERE source_event_id = ANY({source_array});",
        f"DELETE FROM working_memory_entries WHERE source_event_id = ANY({source_array});",
        f"DELETE FROM outbox_jobs WHERE source_event_id = ANY({source_array});",
        (
            "DELETE FROM audit_events "
            f"WHERE source_event_ids && {source_array} "
            f"OR entity_id = ANY({source_array}) "
            f"OR entity_id = ANY({memory_array});"
        ),
        f"DELETE FROM source_events WHERE id = ANY({source_array});",
    ]


def _scope_sql(config: BenchmarkConfig) -> list[str]:
    memwing = config.memwing
    workspace_sql = _nullable_text(memwing.workspace_id)
    shared_group_sql = _nullable_text(memwing.shared_group_id)
    return [
        (
            "INSERT INTO project_memory_spaces (id, name, default_safe_mode_enabled)\n"
            f"VALUES ({_text(memwing.project_memory_space_id)}, 'Benchmark Project', false)\n"
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;"
        ),
        (
            "INSERT INTO runtime_scope_bindings (\n"
            "  runtime, agent_id, workspace_id, session_key_pattern, project_memory_space_id\n"
            ")\n"
            f"VALUES ('openclaw', {_text(memwing.agent_id)}, {workspace_sql}, '*', "
            f"{_text(memwing.project_memory_space_id)})\n"
            "ON CONFLICT DO NOTHING;"
        ),
        (
            "INSERT INTO group_memory_settings (\n"
            "  project_memory_space_id, group_id, safe_mode_enabled, shared_group_id\n"
            ")\n"
            f"VALUES ({_text(memwing.project_memory_space_id)}, {_text(memwing.group_id)}, "
            f"{_bool(memwing.safe_mode)}, {shared_group_sql})\n"
            "ON CONFLICT (project_memory_space_id, group_id)\n"
            "DO UPDATE SET safe_mode_enabled = EXCLUDED.safe_mode_enabled,\n"
            "              shared_group_id = EXCLUDED.shared_group_id;"
        ),
    ]


def _source_event_sql(config: BenchmarkConfig, case: BenchmarkCase) -> list[str]:
    return [_source_event_insert(config, case, message) for message in case.seed_messages]


def _source_event_insert(config: BenchmarkConfig, case: BenchmarkCase, message: SeedMessage) -> str:
    memwing = config.memwing
    metadata = {
        "benchmark_seed": SEED_MARKER,
        "benchmark_case_id": case.case_id,
        "seed_message_id": message.id,
        "message_type": message.message_type,
        "sender": message.sender,
    }
    event_time = message.time or case.case_time
    if not event_time:
        raise ValueError(f"case {case.case_id} message {message.id} is missing time")
    return (
        "INSERT INTO source_events (\n"
        "  id, project_memory_space_id, group_id, thread_id, shared_group_id,\n"
        "  author_id, author_name, source_type, content, content_preview, source_url,\n"
        "  event_time, raw_payload_hash, runtime_event_idempotency_key, metadata_json\n"
        ")\n"
        "VALUES (\n"
        f"  {_text(message.id)}, {_text(memwing.project_memory_space_id)}, {_text(memwing.group_id)}, "
        f"{_text(memwing.thread_id)}, {_nullable_text(memwing.shared_group_id)},\n"
        f"  NULL, {_nullable_text(message.sender)}, 'benchmark.seed', {_text(message.content)}, "
        f"{_text(message.content)}, NULL,\n"
        f"  {_text(event_time)}, {_text(f'benchmark:{case.case_id}:{message.id}')}, NULL, "
        f"{_jsonb(metadata)}\n"
        ")\n"
        "ON CONFLICT (id) DO UPDATE SET\n"
        "  content = EXCLUDED.content,\n"
        "  content_preview = EXCLUDED.content_preview,\n"
        "  metadata_json = EXCLUDED.metadata_json;"
    )


def _memory_item_sql(config: BenchmarkConfig, case: BenchmarkCase) -> list[str]:
    return [_memory_item_insert(config, case, item) for item in case.expected_memory_items]


def _memory_item_insert(config: BenchmarkConfig, case: BenchmarkCase, item: ExpectedMemoryItem) -> str:
    memwing = config.memwing
    source_event_ids = item.gold_evidence_ids
    primary_source_event_id = source_event_ids[0] if source_event_ids else None
    title = _title_for_memory_item(item, case.probes)
    event_time = _event_time_for_memory_item(case, source_event_ids)
    return (
        "INSERT INTO memory_items (\n"
        "  id, project_memory_space_id, group_id, thread_id, shared_group_id,\n"
        "  route, display_type, title, content, summary, source_event_ids,\n"
        "  primary_source_event_id, status, event_time, valid_from, valid_to,\n"
        "  original_score, half_life_days, pinned, created_by, activated_at\n"
        ")\n"
        "VALUES (\n"
        f"  {_text(item.id)}, {_text(memwing.project_memory_space_id)}, {_text(memwing.group_id)}, "
        f"{_text(memwing.thread_id)}, {_nullable_text(memwing.shared_group_id)},\n"
        f"  'manual', 'note', {_text(title)}, {_text(item.fact)}, NULL, {_text_array(source_event_ids)},\n"
        f"  {_nullable_text(primary_source_event_id)}, 'active', {_nullable_text(event_time)}, "
        "NULL, NULL,\n"
        "  1.0, 30, false, 'system', now()\n"
        ")\n"
        "ON CONFLICT (id) DO UPDATE SET\n"
        "  title = EXCLUDED.title,\n"
        "  content = EXCLUDED.content,\n"
        "  source_event_ids = EXCLUDED.source_event_ids,\n"
        "  primary_source_event_id = EXCLUDED.primary_source_event_id,\n"
        "  status = EXCLUDED.status,\n"
        "  activated_at = EXCLUDED.activated_at;"
    )


def _title_for_memory_item(item: ExpectedMemoryItem, probes: list[Probe]) -> str:
    source_ids = set(item.gold_evidence_ids)
    questions = [
        probe.question
        for probe in probes
        if source_ids and source_ids.intersection(probe.gold_evidence_ids)
    ]
    return " / ".join(questions) if questions else item.fact


def _event_time_for_memory_item(case: BenchmarkCase, source_event_ids: list[str]) -> str | None:
    source_id_set = set(source_event_ids)
    for message in case.seed_messages:
        if message.id in source_id_set and message.time:
            return message.time
    return case.case_time


def _case_source_ids(cases: Iterable[BenchmarkCase]) -> list[str]:
    return [message.id for case in cases for message in case.seed_messages]


def _case_memory_ids(cases: Iterable[BenchmarkCase]) -> list[str]:
    return [item.id for case in cases for item in case.expected_memory_items]


def _run_psql(sql: str, *, database_url: str | None) -> None:
    if database_url:
        command = ["psql", database_url, "-X", "-q", "-v", "ON_ERROR_STOP=1"]
        cwd = None
    else:
        command = [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "memwing",
            "-d",
            "memwing",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        cwd = Path(__file__).resolve().parents[2]
    subprocess.run(command, input=sql, text=True, check=True, cwd=cwd)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _nullable_text(value: str | None) -> str:
    if value is None or value == "":
        return "NULL"
    return _text(value)


def _text_array(values: Iterable[str]) -> str:
    return "ARRAY[" + ", ".join(_text(value) for value in values) + "]::text[]"


def _jsonb(value: dict[str, object]) -> str:
    return _text(json.dumps(value, ensure_ascii=False, sort_keys=True)) + "::jsonb"


def _bool(value: bool) -> str:
    return "true" if value else "false"


if __name__ == "__main__":
    app()
