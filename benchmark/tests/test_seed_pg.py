from types import SimpleNamespace

from memwing_benchmark.seed_pg import _run_psql, build_pg_seed_sql, run_pg_seed
from memwing_benchmark.schema import BenchmarkCase, ExpectedMemoryItem, Probe, SeedMessage


def test_pg_seed_sql_replaces_benchmark_case_read_model() -> None:
    case = BenchmarkCase(
        case_id="bs001",
        category="basic",
        case_time="2026-04-25T15:00:00+08:00",
        seed_messages=[
            SeedMessage(
                id="bs001_s1",
                time="2026-04-25T09:21:00+08:00",
                sender="周明",
                content="云帆看板改造项目负责人确定为沈南。",
            )
        ],
        probes=[
            Probe(
                id="bs001_p1",
                question="云帆看板改造项目现在的负责人是谁？",
                gold_answer="沈南",
                gold_evidence_ids=["bs001_s1"],
            )
        ],
        expected_memory_items=[
            ExpectedMemoryItem(
                id="bs001_m1",
                fact="云帆看板改造项目负责人是沈南。",
                gold_evidence_ids=["bs001_s1"],
            )
        ],
    )

    sql = build_pg_seed_sql(
        config=_config(),
        target_cases=[case],
        cleanup_cases=[case],
        action="replace",
    )

    assert sql.index("DELETE FROM memory_recall_events") < sql.index("DELETE FROM memory_items")
    assert sql.index("DELETE FROM memory_items") < sql.index("DELETE FROM source_events")
    assert "INSERT INTO project_memory_spaces" in sql
    assert "INSERT INTO runtime_scope_bindings" in sql
    assert "INSERT INTO source_events" in sql
    assert "INSERT INTO memory_items" in sql
    assert "'bs001_s1'" in sql
    assert "'bs001_m1'" in sql
    assert "'云帆看板改造项目现在的负责人是谁？'" in sql
    assert "'云帆看板改造项目负责人是沈南。'" in sql
    assert "\"benchmark_seed\": \"memwing_benchmark_pg_seed\"" in sql


def test_pg_seed_cleanup_all_can_delete_previous_case_without_seeding_it() -> None:
    previous = BenchmarkCase(
        case_id="bs001",
        category="basic",
        seed_messages=[SeedMessage(id="bs001_s1", content="old")],
        expected_memory_items=[ExpectedMemoryItem(id="bs001_m1", fact="old")],
    )
    current = BenchmarkCase(
        case_id="lt001",
        category="basic",
        seed_messages=[SeedMessage(id="lt001_s1", time="2026-04-25T09:00:00+08:00", content="new")],
        expected_memory_items=[ExpectedMemoryItem(id="lt001_m1", fact="new")],
    )

    sql = build_pg_seed_sql(
        config=_config(),
        target_cases=[current],
        cleanup_cases=[previous, current],
        action="replace",
    )

    assert "DELETE FROM memory_items WHERE id = ANY(ARRAY['bs001_m1', 'lt001_m1']::text[]);" in sql
    assert "DELETE FROM source_events WHERE id = ANY(ARRAY['bs001_s1', 'lt001_s1']::text[]);" in sql
    assert "VALUES (\n  'lt001_s1'" in sql
    assert "VALUES (\n  'bs001_s1'" not in sql


def test_run_pg_seed_executes_sql_and_returns_sanitized_summary(monkeypatch) -> None:
    case = BenchmarkCase(
        case_id="bs001",
        category="basic",
        case_time="2026-04-25T15:00:00+08:00",
        seed_messages=[SeedMessage(id="bs001_s1", content="seed")],
        expected_memory_items=[ExpectedMemoryItem(id="bs001_m1", fact="fact")],
    )
    captured = {}

    def fake_run_psql(sql, *, database_url):
        captured["sql"] = sql
        captured["database_url"] = database_url

    monkeypatch.setattr("memwing_benchmark.seed_pg._run_psql", fake_run_psql)

    summary = run_pg_seed(
        config=_config(),
        target_cases=[case],
        cleanup_cases=[case],
        action="replace",
        database_url="postgresql://user:secret@localhost/memwing",
    )

    assert "INSERT INTO source_events" in captured["sql"]
    assert captured["database_url"] == "postgresql://user:secret@localhost/memwing"
    assert summary == {
        "action": "replace",
        "target_case_ids": ["bs001"],
        "cleanup_case_ids": ["bs001"],
        "target_source_event_count": 1,
        "target_memory_item_count": 1,
        "cleanup_source_event_count": 1,
        "cleanup_memory_item_count": 1,
        "runner": "database_url",
    }


def test_run_psql_uses_quiet_psql_flags(monkeypatch) -> None:
    captured = {}

    def fake_subprocess_run(command, *, input, text, check, cwd):
        captured["command"] = command
        captured["input"] = input
        captured["text"] = text
        captured["check"] = check
        captured["cwd"] = cwd

    monkeypatch.setattr("memwing_benchmark.seed_pg.subprocess.run", fake_subprocess_run)

    _run_psql("BEGIN; COMMIT;", database_url="postgresql://memwing@localhost/memwing")

    assert captured["command"] == [
        "psql",
        "postgresql://memwing@localhost/memwing",
        "-X",
        "-q",
        "-v",
        "ON_ERROR_STOP=1",
    ]
    assert captured["input"] == "BEGIN; COMMIT;"
    assert captured["text"] is True
    assert captured["check"] is True
    assert captured["cwd"] is None


def _config():
    return SimpleNamespace(
        memwing=SimpleNamespace(
            project_memory_space_id="project_001",
            group_id="benchmark_group",
            thread_id="benchmark_thread",
            shared_group_id="",
            workspace_id="workspace_001",
            agent_id="main",
            safe_mode=True,
        )
    )
