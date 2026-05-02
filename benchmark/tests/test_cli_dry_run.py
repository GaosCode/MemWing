from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from memwing_benchmark.adapters.openclaw_native import ConfigValue, MemorySearchDetails
from memwing_benchmark.cli import (
    _prepare_live_chat,
    _prepare_live_workspace,
    _poll_memwing_readiness,
    _restore_live_workspace,
    _run_memwing_retrieval_batch,
    _run_offline_batch,
    _run_live,
    _run_write_evaluate_batch,
    _run_write_ingest_batch,
    _run_write_live_batch,
    app,
    make_idempotency_key,
)
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluators.llm_judge import (
    AnswerJudgeBlock,
    JudgeResult,
    RetrievalJudgeBlock,
    WriteJudgeBlock,
)
from memwing_benchmark.json_utils import dumps_json, loads_json
from memwing_benchmark.schema import BenchmarkCase, Probe, SeedMessage


def test_cli_non_live_creates_run_outputs(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--config",
            "config.example.json",
            "--backend",
            "openclaw-native",
            "--cases",
            "datasets",
            "--case-id",
            "bs001",
            "--runs-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    mode_dir = tmp_path / "retrieval"
    assert mode_dir.exists()
    day_dirs = list(mode_dir.iterdir())
    assert len(day_dirs) == 1
    run_dirs = list(day_dirs[0].iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "normalized.jsonl").exists()
    assert (run_dirs[0] / "scores.json").exists()
    assert (run_dirs[0] / "report.md").exists()


def test_cli_uses_datasets_as_default_cases_path(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--config",
            "config.example.json",
            "--backend",
            "openclaw-native",
            "--mode",
            "retrieval",
            "--case-id",
            "bs001",
            "--runs-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "retrieval").exists()


def test_cli_requires_single_case_without_batch() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--config",
            "config.example.json",
            "--backend",
            "openclaw-native",
            "--cases",
            "datasets",
        ],
    )

    assert result.exit_code == 1
    assert "non-batch runs require exactly one case" in result.output


def test_cli_validates_memwing_config_before_dispatch(tmp_path: Path) -> None:
    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "memwing": {
                    "base_url": "",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                }
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "--backend",
            "memwing-http",
            "--mode",
            "retrieval",
            "--case-id",
            "bs001",
        ],
    )

    assert result.exit_code == 1
    assert "memwing.base_url is required" in result.output


def test_cli_memwing_retrieval_creates_run_outputs(monkeypatch, tmp_path: Path) -> None:
    class FakeMemWingAdapter:
        def __init__(self, _config):
            self.records = []

        def ingest_seed_messages(self, *, case, run_id):
            return [
                {
                    "case_id": case.case_id,
                    "seed_message_id": "bs001_s1",
                    "accepted": True,
                    "source_event_id": "source_event_001",
                    "trace_id": "trace_ingest",
                    "latency_ms": 3,
                }
            ]

        def memory_search_details(self, question, *, max_results):
            return MemorySearchDetails(
                contexts=["云帆看板改造项目负责人确定为沈南。"],
                results=[
                    {
                        "rank": 1,
                        "score": 0.91,
                        "source": "memory_item",
                        "snippet": "云帆看板改造项目负责人确定为沈南。",
                        "source_event_ids": ["source_event_001"],
                    }
                ],
                latency_ms=7,
                raw={"trace_id": "trace_search", "results": []},
            )

    class FakeJudge:
        def evaluate_retrieval(self, **kwargs):
            return JudgeResult(
                judge_type="offline_retrieval",
                case_id=kwargs["case_id"],
                probe_id=kwargs["probe"].id,
                retrieval=RetrievalJudgeBlock(
                    recall_at_1=True,
                    recall_at_3=True,
                    recall_at_5=True,
                    matched_gold_memory_ids=kwargs["probe"].gold_evidence_ids,
                ),
            )

    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "paths": {"runs_dir": str(tmp_path / "runs")},
                "memwing": {
                    "base_url": "http://memwing.test",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                    "poll_interval_seconds": 0.01,
                    "poll_timeout_seconds": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("memwing_benchmark.cli.MemWingAdapter", FakeMemWingAdapter)
    monkeypatch.setattr("memwing_benchmark.cli._build_judge", lambda _config: FakeJudge())

    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config_path),
            "--backend",
            "memwing-http",
            "--cases",
            "datasets",
            "--case-id",
            "bs001",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    run_dir = Path(result.output.strip().splitlines()[-1])
    run_config = loads_json((run_dir / "config.json").read_bytes())
    normalized = loads_json((run_dir / "normalized.jsonl").read_text().splitlines()[0])
    raw_records = loads_json((run_dir / "raw" / "records.json").read_bytes())
    assert run_config["backend"] == "memwing-http"
    assert normalized["backend"] == "memwing-http"
    assert normalized["durable_memory_available"] is True
    assert normalized["retrieved_evidence_ids"] == ["source_event_001"]
    assert raw_records["memwing_polls"][0]["durable_memory_available"] is True


def test_cli_memwing_write_ingest_uses_http_ingest_without_live(monkeypatch, tmp_path: Path) -> None:
    class FakeMemWingAdapter:
        def __init__(self, _config):
            self.records = [{"endpoint": "/v1/openclaw/events/ingest", "status_code": 202}]

        def ingest_seed_messages(self, *, case, run_id):
            return [
                {
                    "case_id": case.case_id,
                    "seed_message_id": "bs001_s1",
                    "accepted": True,
                    "source_event_id": "source_event_001",
                    "trace_id": "trace_ingest",
                    "latency_ms": 3,
                }
            ]

    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "paths": {"runs_dir": str(tmp_path / "runs")},
                "memwing": {
                    "base_url": "http://memwing.test",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("memwing_benchmark.cli.MemWingAdapter", FakeMemWingAdapter)
    monkeypatch.setattr("memwing_benchmark.cli._build_judge", lambda _config: None)

    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config_path),
            "--backend",
            "memwing",
            "--mode",
            "write",
            "--phase",
            "ingest",
            "--cases",
            "datasets",
            "--case-id",
            "bs001",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    run_dir = Path(result.output.strip().splitlines()[-1])
    run_config = loads_json((run_dir / "config.json").read_bytes())
    normalized = loads_json((run_dir / "normalized.jsonl").read_text().splitlines()[0])
    raw_records = loads_json((run_dir / "raw" / "records.json").read_bytes())
    assert run_config["backend"] == "memwing-http"
    assert run_config["mode"] == "write"
    assert run_config["phase"] == "ingest"
    assert run_config["live"] is False
    assert normalized["backend"] == "memwing-http"
    assert normalized["raw"]["mode"] == "memory_write_ingest"
    assert normalized["raw"]["backend"] == "memwing-http"
    assert len(normalized["seed_message_ids"]) == 13
    assert raw_records["memwing_ingest"][0]["source_event_id"] == "source_event_001"
    assert raw_records["memory_writes"][0]["phase"] == "ingest"


def test_cli_memwing_write_evaluate_scores_search_without_file_metrics(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeMemWingAdapter:
        def __init__(self, _config):
            self.records = []

        def memory_search_details(self, question, *, max_results):
            assert max_results == 5
            return MemorySearchDetails(
                contexts=[f"MemWing memory: {question}"],
                results=[
                    {
                        "rank": 1,
                        "score": 0.91,
                        "source": "memory_item",
                        "snippet": question,
                        "source_event_ids": ["source_event_001"],
                    }
                ],
                latency_ms=7,
                raw={"trace_id": "trace_search", "results": []},
            )

    class FakeJudge:
        def evaluate_write(self, **kwargs):
            assert len(kwargs["written_context"]) == 4
            assert "MemWing memory: 云帆看板改造项目负责人是沈南。" in kwargs[
                "written_context"
            ]
            assert kwargs["allowed_other_memories"] == []
            return JudgeResult(
                judge_type="memory_write",
                case_id=kwargs["case_id"],
                probe_id="bs001_write",
                write=WriteJudgeBlock(
                    write_recall=1.0,
                    write_precision=1.0,
                    written_claim_count=1,
                    matched_expected_memory_ids=["bs001_m1"],
                    missing_expected_memory_ids=[],
                ),
            )

    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "paths": {"runs_dir": str(tmp_path / "runs")},
                "memwing": {
                    "base_url": "http://memwing.test",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                },
                "judge": {"provider": "volcengine-ark", "api_key": "sk_test"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("memwing_benchmark.cli.MemWingAdapter", FakeMemWingAdapter)
    monkeypatch.setattr("memwing_benchmark.cli._build_judge", lambda _config: FakeJudge())

    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config_path),
            "--backend",
            "memwing",
            "--mode",
            "write",
            "--phase",
            "evaluate",
            "--cases",
            "datasets",
            "--case-id",
            "bs001",
            "--runs-dir",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code == 0, result.output
    run_dir = Path(result.output.strip().splitlines()[-1])
    normalized = loads_json((run_dir / "normalized.jsonl").read_text().splitlines()[0])
    raw_records = loads_json((run_dir / "raw" / "records.json").read_bytes())
    assert normalized["backend"] == "memwing-http"
    assert normalized["write_recall"] == 1.0
    assert normalized["write_precision"] == 1.0
    assert normalized["write_changed_file_count"] is None
    assert normalized["raw"]["changed_file_metrics_available"] is False
    assert "HTTP search APIs" in normalized["raw"]["changed_file_metrics_missing_reason"]
    assert raw_records["memory_writes"][0]["changed_file_metrics_available"] is False
    assert raw_records["memory_searches"][0]["mode"] == "memwing_write_evaluate"


def test_cli_memwing_openclaw_plugin_preflight_fails_before_feishu(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeOpenClawAdapter:
        commands = []

        def __init__(self, *_args, **_kwargs):
            pass

        def get_config_value(self, path):
            if path == "plugins.entries.memwing.enabled":
                return ConfigValue(present=True, value=True)
            if path == "plugins.entries.memwing.hooks.allowConversationAccess":
                return ConfigValue(present=True, value=True)
            if path == "plugins.entries.memwing.config.memwingBaseUrl":
                return ConfigValue(present=True, value="http://wrong-memwing.test")
            return ConfigValue(present=False)

    class UnexpectedFeishu:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Feishu must not be touched before plugin preflight passes")

    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "paths": {
                    "openclaw_repo_dir": "/tmp/openclaw",
                    "runs_dir": str(tmp_path / "runs"),
                },
                "feishu": {"chat_id": "oc_seed"},
                "memwing": {
                    "base_url": "http://memwing.test/",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("memwing_benchmark.cli.OpenClawNativeAdapter", FakeOpenClawAdapter)
    monkeypatch.setattr("memwing_benchmark.cli.FeishuCli", UnexpectedFeishu)
    monkeypatch.setattr("memwing_benchmark.cli._build_judge", lambda _config: None)

    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config_path),
            "--backend",
            "memwing-openclaw-plugin",
            "--mode",
            "write",
            "--phase",
            "ingest",
            "--cases",
            "datasets",
            "--case-id",
            "bs001",
            "--live",
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert "OpenClaw MemWing plugin config does not match memwing.base_url" in result.output


def test_cli_memwing_openclaw_plugin_live_ingest_uses_feishu_not_http_ingest(
    monkeypatch, tmp_path: Path
) -> None:
    sent_messages = []
    searched_questions = []

    class FakeOpenClawAdapter:
        commands = []

        def __init__(self, *_args, **_kwargs):
            pass

        def get_config_value(self, path):
            if path == "plugins.entries.memwing.enabled":
                return ConfigValue(present=True, value=True)
            if path == "plugins.entries.memwing.hooks.allowConversationAccess":
                return ConfigValue(present=True, value=True)
            if path == "plugins.entries.memwing.config.memwingBaseUrl":
                return ConfigValue(present=True, value="http://memwing.test")
            return ConfigValue(present=False)

        def get_default_workspace(self):
            return tmp_path / "openclaw-workspace"

    class FakeFeishu:
        commands = []

        def __init__(self, _bin):
            pass

        def ensure_ready(self, *, required_scopes):
            assert required_scopes == ["im:message.send_as_user"]

        def send_text(self, *, chat_id, text, idempotency_key):
            sent_messages.append((chat_id, text, idempotency_key))
            return {"message_id": f"msg_{len(sent_messages)}", "chat_id": chat_id}

    class FakeMemWingAdapter:
        def __init__(self, _config):
            self.records = []

        def ingest_seed_messages(self, *, case, run_id):
            raise AssertionError("plugin live ingest must not call MemWing HTTP ingest directly")

        def memory_search_details(self, question, *, max_results):
            searched_questions.append((question, max_results))
            return MemorySearchDetails(
                contexts=[f"MemWing plugin memory: {question}"],
                results=[
                    {
                        "rank": 1,
                        "score": 0.91,
                        "source": "memory_item",
                        "snippet": question,
                        "source_event_ids": ["source_event_001"],
                    }
                ],
                latency_ms=7,
                raw={"trace_id": "trace_search", "results": []},
            )

    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "paths": {
                    "openclaw_repo_dir": "/tmp/openclaw",
                    "runs_dir": str(tmp_path / "runs"),
                },
                "feishu": {"chat_id": "oc_seed"},
                "memwing": {
                    "base_url": "http://memwing.test/",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                    "poll_interval_seconds": 0.01,
                    "poll_timeout_seconds": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("memwing_benchmark.cli.OpenClawNativeAdapter", FakeOpenClawAdapter)
    monkeypatch.setattr("memwing_benchmark.cli.FeishuCli", FakeFeishu)
    monkeypatch.setattr("memwing_benchmark.cli.MemWingAdapter", FakeMemWingAdapter)
    monkeypatch.setattr("memwing_benchmark.cli._build_judge", lambda _config: None)

    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config_path),
            "--backend",
            "memwing-openclaw-plugin",
            "--mode",
            "write",
            "--phase",
            "ingest",
            "--cases",
            "datasets",
            "--case-id",
            "bs001",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--message-interval-seconds",
            "0",
            "--live",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    run_dir = Path(result.output.strip().splitlines()[-1])
    run_config = loads_json((run_dir / "config.json").read_bytes())
    normalized = loads_json((run_dir / "normalized.jsonl").read_text().splitlines()[0])
    raw_records = loads_json((run_dir / "raw" / "records.json").read_bytes())
    assert run_config["backend"] == "memwing-openclaw-plugin"
    assert normalized["backend"] == "memwing-openclaw-plugin"
    assert sent_messages
    assert searched_questions
    assert raw_records["memwing_ingest"] == []
    assert raw_records["memwing_polls"][0]["mode"] == "memwing_openclaw_plugin_write_ingest"
    assert raw_records["memwing_polls"][0]["durable_memory_available"] is True
    assert raw_records["feishu"][0]["kind"] == "write_ingest_seed"


def test_cli_memwing_openclaw_plugin_evaluate_uses_memwing_search_not_files(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeOpenClawAdapter:
        commands = []

        def __init__(self, *_args, **_kwargs):
            pass

        def get_config_value(self, path):
            if path == "plugins.entries.memwing.enabled":
                return ConfigValue(present=True, value=True)
            if path == "plugins.entries.memwing.hooks.allowConversationAccess":
                return ConfigValue(present=True, value=True)
            if path == "plugins.entries.memwing.config.memwingBaseUrl":
                return ConfigValue(present=True, value="http://memwing.test")
            return ConfigValue(present=False)

        def get_default_workspace(self):
            raise AssertionError("plugin evaluate must not read OpenClaw native memory files")

    class FakeMemWingAdapter:
        def __init__(self, _config):
            self.records = []

        def memory_search_details(self, question, *, max_results):
            assert max_results == 5
            return MemorySearchDetails(
                contexts=[f"MemWing plugin memory: {question}"],
                results=[
                    {
                        "rank": 1,
                        "score": 0.91,
                        "source": "memory_item",
                        "snippet": question,
                        "source_event_ids": ["source_event_001"],
                    }
                ],
                latency_ms=7,
                raw={"trace_id": "trace_search", "results": []},
            )

    class FakeJudge:
        def evaluate_write(self, **kwargs):
            assert kwargs["written_context"]
            assert kwargs["case_id"] == "bs001"
            return JudgeResult(
                judge_type="memory_write",
                case_id=kwargs["case_id"],
                probe_id="bs001_write",
                write=WriteJudgeBlock(
                    write_recall=1.0,
                    write_precision=1.0,
                    written_claim_count=1,
                    matched_expected_memory_ids=["bs001_m1"],
                    missing_expected_memory_ids=[],
                ),
            )

    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "paths": {
                    "openclaw_repo_dir": "/tmp/openclaw",
                    "runs_dir": str(tmp_path / "runs"),
                },
                "memwing": {
                    "base_url": "http://memwing.test/",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                },
                "judge": {"provider": "volcengine-ark", "api_key": "sk_test"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("memwing_benchmark.cli.OpenClawNativeAdapter", FakeOpenClawAdapter)
    monkeypatch.setattr("memwing_benchmark.cli.MemWingAdapter", FakeMemWingAdapter)
    monkeypatch.setattr("memwing_benchmark.cli._build_judge", lambda _config: FakeJudge())

    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config_path),
            "--backend",
            "memwing-openclaw-plugin",
            "--mode",
            "write",
            "--phase",
            "evaluate",
            "--cases",
            "datasets",
            "--case-id",
            "bs001",
            "--runs-dir",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code == 0, result.output
    run_dir = Path(result.output.strip().splitlines()[-1])
    normalized = loads_json((run_dir / "normalized.jsonl").read_text().splitlines()[0])
    raw_records = loads_json((run_dir / "raw" / "records.json").read_bytes())
    assert normalized["backend"] == "memwing-openclaw-plugin"
    assert normalized["write_recall"] == 1.0
    assert normalized["write_changed_file_count"] is None
    assert raw_records["memory_searches"][0]["mode"] == "memwing_write_evaluate"


def test_offline_batch_uses_default_workspace_per_case(tmp_path: Path) -> None:
    original_workspace = str(tmp_path / "openclaw-workspace")
    preseed_cases = []
    searches = []

    class FakeAdapter:
        commands = []

        def get_default_workspace(self):
            return original_workspace

        def preseed_long_term_memories(self, *, cases, run_id):
            preseed_cases.append([case.case_id for case in cases])
            return tmp_path / f"{cases[0].case_id}-preseed.md"

        def memory_search_details(self, question, *, max_results):
            searches.append((question, max_results))
            return MemorySearchDetails(
                contexts=[f"retrieved context for {question}"],
                results=[
                    {
                        "rank": 1,
                        "path": "memory/memwing-benchmark-preseed.md",
                        "score": 0.91,
                        "vectorScore": 0.81,
                        "textScore": 0.1,
                        "snippet": f"retrieved context for {question}",
                    }
                ],
                latency_ms=7,
                raw={"results": []},
            )

    class FakeJudge:
        def evaluate_retrieval(self, **kwargs):
            return JudgeResult(
                judge_type="offline_retrieval",
                case_id=kwargs["case_id"],
                probe_id=kwargs["probe"].id,
                retrieval=RetrievalJudgeBlock(
                    recall_at_1=True,
                    recall_at_3=True,
                    recall_at_5=True,
                    matched_gold_memory_ids=kwargs["probe"].gold_evidence_ids,
                ),
            )

    cases = [
        BenchmarkCase(
            case_id="bs001",
            category="long_term_preseed",
            seed_messages=[SeedMessage(id="bs001_s1", content="云帆负责人是沈南。")],
            probes=[
                Probe(
                    id="bs001_p1",
                    question="云帆负责人是谁？",
                    gold_answer="沈南",
                    gold_evidence_ids=["bs001_s1"],
                )
            ],
        ),
        BenchmarkCase(
            case_id="lt001",
            category="long_term_preseed",
            seed_messages=[SeedMessage(id="lt001_s1", content="蓝桥负责人是许宁。")],
            probes=[
                Probe(
                    id="lt001_p1",
                    question="蓝桥负责人是谁？",
                    gold_answer="许宁",
                    gold_evidence_ids=["lt001_s1"],
                )
            ],
        ),
    ]
    raw_records = {"memory_searches": [], "side_effects": [], "debug": []}
    run_dir = tmp_path / "runs" / "offline-batch" / "20260427" / "run1"

    results = _run_offline_batch(
        run_id="run1",
        backend="openclaw-native",
        cases=cases,
        config=SimpleNamespace(
            feishu=SimpleNamespace(chat_id=""),
            openclaw=SimpleNamespace(workspace_dir=""),
        ),
        adapter=FakeAdapter(),
        judge=FakeJudge(),
        raw_records=raw_records,
        run_dir=run_dir,
        yes=True,
    )

    assert [result.case_id for result in results] == ["bs001", "lt001"]
    assert preseed_cases == [["bs001"], ["lt001"]]
    assert searches == [("云帆负责人是谁？", 5), ("蓝桥负责人是谁？", 5)]
    assert [record["case_id"] for record in raw_records["memory_searches"]] == [
        "bs001",
        "lt001",
    ]
    assert "离线检索完成" in {record["message"] for record in raw_records["debug"]}
    assert raw_records["side_effects"][-1] == {
        "action": "offline_batch_case_completed",
        "case_id": "lt001",
        "workspace": original_workspace,
    }


def test_memwing_retrieval_batch_records_readiness_timeout() -> None:
    class FakeAdapter:
        def ingest_seed_messages(self, *, case, run_id):
            return [
                {
                    "case_id": case.case_id,
                    "seed_message_id": "bs001_s1",
                    "source_event_id": "source_event_001",
                }
            ]

        def memory_search_details(self, question, *, max_results):
            return MemorySearchDetails(
                contexts=[],
                results=[],
                latency_ms=4,
                raw={"trace_id": "trace_empty", "results": []},
            )

    case = BenchmarkCase(
        case_id="bs001",
        category="basic",
        seed_messages=[SeedMessage(id="bs001_s1", content="负责人是沈南。")],
        probes=[
            Probe(
                id="bs001_p1",
                question="负责人是谁？",
                gold_answer="沈南",
                gold_evidence_ids=["bs001_s1"],
            )
        ],
    )
    raw_records = {
        "memwing_ingest": [],
        "memwing_polls": [],
        "memory_searches": [],
        "side_effects": [],
        "debug": [],
    }

    results = _run_memwing_retrieval_batch(
        run_id="run1",
        backend="memwing",
        cases=[case],
        adapter=FakeAdapter(),
        judge=None,
        raw_records=raw_records,
        poll_interval_seconds=0.01,
        timeout_seconds=0,
        yes=True,
    )

    assert results[0].durable_memory_available is False
    assert results[0].extraction_timeout is True
    assert raw_records["memwing_polls"][0]["extraction_timeout"] is True
    assert raw_records["memwing_polls"][0]["attempts"][0]["durable_memory_available"] is False


def test_memwing_readiness_records_server_error() -> None:
    class FakeAdapter:
        def memory_search_details(self, question, *, max_results):
            raise BenchmarkError("MemWing request failed: endpoint=/v1/memwing/tools/search-memory")

    poll = _poll_memwing_readiness(
        adapter=FakeAdapter(),
        query="负责人是谁？",
        expected_source_event_ids=["source_event_001"],
        poll_interval_seconds=0.01,
        timeout_seconds=0,
    )

    assert poll.durable_memory_available is False
    assert poll.extraction_timeout is True
    assert "MemWing request failed" in poll.search_error
    assert "MemWing request failed" in poll.attempts[0]["memory_search_error"]


def test_write_live_sends_seed_without_flush_and_scores_memory_diff(
    monkeypatch, tmp_path: Path
) -> None:
    sent_messages = []
    workspace = tmp_path / "workspace"
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True)

    class FakeFeishu:
        commands = []

        def __init__(self, _bin):
            pass

        def ensure_ready(self, *, required_scopes):
            assert required_scopes == ["im:message.send_as_user"]

        def send_text(self, *, chat_id, text, idempotency_key):
            sent_messages.append((chat_id, text))
            (memory_dir / "2026-04-27.md").write_text(
                "云帆看板改造项目负责人确定为沈南。\n",
                encoding="utf-8",
            )
            return {"message_id": f"msg_{len(sent_messages)}", "chat_id": chat_id}

    class FakeAdapter:
        commands = []

        def get_default_workspace(self):
            return workspace

    class FakeJudge:
        def evaluate_write(self, **kwargs):
            assert kwargs["written_context"] == ["云帆看板改造项目负责人确定为沈南。"]
            return JudgeResult(
                judge_type="memory_write",
                case_id=kwargs["case_id"],
                probe_id="bs001_write",
                write=WriteJudgeBlock(
                    write_recall=1.0,
                    write_precision=1.0,
                    written_claim_count=1,
                    matched_expected_memory_ids=["bs001_m1"],
                    missing_expected_memory_ids=[],
                ),
            )

    monkeypatch.setattr("memwing_benchmark.cli.FeishuCli", FakeFeishu)
    case = BenchmarkCase(
        case_id="bs001",
        category="long_term_preseed",
        seed_messages=[SeedMessage(id="bs001_s1", content="云帆负责人是沈南。")],
        expected_memory_items=[
            {"id": "bs001_m1", "fact": "云帆看板改造项目负责人确定为沈南。"}
        ],
    )
    raw_records = {"feishu": [], "feishu_commands": [], "memory_writes": [], "side_effects": []}

    results = _run_write_live_batch(
        run_id="run1",
        backend="openclaw-native",
        cases=[case],
        config=SimpleNamespace(feishu=SimpleNamespace(cli_bin="lark-cli")),
        adapter=FakeAdapter(),
        chats=SimpleNamespace(seed_chat_id="oc_seed", probe_chat_id="oc_probe"),
        judge=FakeJudge(),
        raw_records=raw_records,
        message_interval_seconds=0,
        settle_seconds=0,
        memory_poll_interval_seconds=20,
        memory_timeout_seconds=0,
    )

    assert sent_messages == [("oc_seed", "云帆负责人是沈南。")]
    assert [record["kind"] for record in raw_records["feishu"]] == ["write_seed"]
    assert results[0].probe_id == "bs001_write"
    assert results[0].write_recall == 1.0
    assert results[0].write_precision == 1.0
    assert results[0].write_changed_file_count == 1
    assert "云帆看板改造项目负责人确定为沈南" in results[0].written_contexts[0]


def test_write_ingest_batch_sends_all_cases_to_one_chat(monkeypatch, tmp_path: Path) -> None:
    sent_messages = []

    class FakeFeishu:
        commands = []

        def __init__(self, _bin):
            pass

        def ensure_ready(self, *, required_scopes):
            assert required_scopes == ["im:message.send_as_user"]

        def send_text(self, *, chat_id, text, idempotency_key):
            sent_messages.append((chat_id, text, idempotency_key))
            return {"message_id": f"msg_{len(sent_messages)}", "chat_id": chat_id}

    class FakeAdapter:
        def get_default_workspace(self):
            return tmp_path / "workspace"

    monkeypatch.setattr("memwing_benchmark.cli.FeishuCli", FakeFeishu)
    cases = [
        BenchmarkCase(
            case_id="bs001",
            category="long_term_preseed",
            seed_messages=[SeedMessage(id="bs001_s1", content="负责人是沈南。")],
        ),
        BenchmarkCase(
            case_id="bs002",
            category="long_term_preseed",
            seed_messages=[SeedMessage(id="bs002_s1", content="验收人是韩悦。")],
        ),
    ]
    raw_records = {"feishu": [], "feishu_commands": [], "memory_writes": [], "side_effects": []}

    results = _run_write_ingest_batch(
        run_id="run1",
        backend="openclaw-native",
        cases=cases,
        config=SimpleNamespace(feishu=SimpleNamespace(cli_bin="lark-cli")),
        adapter=FakeAdapter(),
        chats=SimpleNamespace(seed_chat_id="oc_ingest", probe_chat_id="oc_ingest"),
        raw_records=raw_records,
        message_interval_seconds=0,
    )

    assert [item[:2] for item in sent_messages] == [
        ("oc_ingest", "负责人是沈南。"),
        ("oc_ingest", "验收人是韩悦。"),
    ]
    assert [record["kind"] for record in raw_records["feishu"]] == [
        "write_ingest_seed",
        "write_ingest_seed",
    ]
    assert raw_records["memory_writes"][0]["phase"] == "ingest"
    assert raw_records["memory_writes"][0]["sent_message_count"] == 2
    assert [result.raw["phase"] for result in results] == ["ingest", "ingest"]


def test_write_evaluate_batch_scores_current_workspace_memory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "2026-04-27.md").write_text(
        "云帆看板改造项目负责人确定为沈南。\n验收人是韩悦。\n",
        encoding="utf-8",
    )
    seen_kwargs = []

    class FakeAdapter:
        def get_default_workspace(self):
            return workspace

    class FakeJudge:
        def evaluate_write(self, **kwargs):
            seen_kwargs.append(kwargs)
            return JudgeResult(
                judge_type="memory_write",
                case_id=kwargs["case_id"],
                probe_id=f"{kwargs['case_id']}_write",
                write=WriteJudgeBlock(
                    write_recall=1.0,
                    write_precision=1.0,
                    written_claim_count=1,
                    matched_expected_memory_ids=[kwargs["expected_memories"][0].id],
                    missing_expected_memory_ids=[],
                ),
            )

    cases = [
        BenchmarkCase(
            case_id="bs001",
            category="long_term_preseed",
            expected_memory_items=[
                {"id": "bs001_m1", "fact": "云帆看板改造项目负责人确定为沈南。"}
            ],
        ),
        BenchmarkCase(
            case_id="bs002",
            category="long_term_preseed",
            expected_memory_items=[{"id": "bs002_m1", "fact": "验收人是韩悦。"}],
        ),
    ]
    raw_records = {"memory_writes": [], "side_effects": []}

    results = _run_write_evaluate_batch(
        run_id="run1",
        backend="openclaw-native",
        cases=cases,
        adapter=FakeAdapter(),
        judge=FakeJudge(),
        raw_records=raw_records,
        chat_id=None,
    )

    assert len(seen_kwargs) == 2
    assert "Source: memory/2026-04-27.md" in seen_kwargs[0]["written_context"][0]
    assert seen_kwargs[0]["allowed_other_memories"][0].id == "bs002_m1"
    assert [result.write_recall for result in results] == [1.0, 1.0]
    assert results[0].raw["phase"] == "evaluate"
    assert raw_records["memory_writes"][0]["phase"] == "evaluate"


def test_idempotency_key_is_short_stable_and_traceable() -> None:
    key = make_idempotency_key(
        run_id="20260425-133837",
        backend="openclaw-native",
        case_id="bs001",
        item_id="bs001_s1",
    )

    assert key == make_idempotency_key(
        run_id="20260425-133837",
        backend="openclaw-native",
        case_id="bs001",
        item_id="bs001_s1",
    )
    assert len(key) <= 50
    assert key.startswith("mwb-bs001-bs001-s1-")
    assert "_" not in key


def test_live_run_sends_seed_then_probe(monkeypatch, tmp_path: Path) -> None:
    sent_messages = []

    class FakeFeishu:
        commands = []
        reply_count = 0

        def __init__(self, _bin):
            pass

        def ensure_ready(self, *, required_scopes):
            assert required_scopes == ["im:message.send_as_user"]

        def send_text(self, *, chat_id, text, idempotency_key):
            sent_messages.append((chat_id, text))
            return {"message_id": f"msg_{len(sent_messages)}", "chat_id": chat_id}

        def wait_for_bot_reply(self, **_kwargs):
            self.reply_count += 1
            if self.reply_count == 1:
                return {"message_id": "flush_reply_1", "content": "MEMWING_SEED_FLUSH_READY"}
            if self.reply_count == 2:
                return {"message_id": "flush_commit_reply_1", "content": "MEMWING_SEED_FLUSH_DONE"}
            return {"message_id": "reply_1", "content": "负责人是沈南。"}

    class FakeAdapter:
        commands = []
        index_count = 0
        search_count = 0

        def preseed_long_term_memories(self, *, cases, run_id):
            return tmp_path / "memwing-benchmark-preseed.md"

        def memory_index(self):
            self.index_count += 1

        def memory_search(self, question, *, max_results):
            self.search_count += 1
            return ["云帆看板改造项目负责人确定为沈南。"]

        def memory_search_details(self, question, *, max_results):
            self.search_count += 1
            return MemorySearchDetails(
                contexts=["云帆看板改造项目负责人确定为沈南。"],
                results=[
                    {
                        "rank": 1,
                        "path": "memory/2026-04-26.md",
                        "startLine": 1,
                        "endLine": 2,
                        "score": 0.9,
                        "vectorScore": 0.8,
                        "textScore": 0.1,
                        "source": "memory",
                        "snippet": "云帆看板改造项目负责人确定为沈南。",
                    }
                ],
                latency_ms=12,
                raw={"results": []},
            )

    class FakeJudge:
        def evaluate_retrieval(self, **kwargs):
            return JudgeResult(
                judge_type="offline_retrieval",
                case_id=kwargs["case_id"],
                probe_id=kwargs["probe"].id,
                retrieval=RetrievalJudgeBlock(
                    recall_at_1=True,
                    recall_at_3=True,
                    recall_at_5=True,
                    matched_gold_memory_ids=["bs001_s1"],
                ),
            )

        def evaluate_answer(self, **kwargs):
            return JudgeResult(
                judge_type="online_answer",
                case_id=kwargs["case_id"],
                probe_id=kwargs["probe"].id,
                answer=AnswerJudgeBlock(
                    answer_score=2,
                    answer_correct=True,
                    evidence_correct=True,
                    temporal_correct=None,
                    noise_polluted=False,
                    matched_gold_memory_ids=["bs001_s1"],
                ),
            )

    monkeypatch.setattr("memwing_benchmark.cli.FeishuCli", FakeFeishu)
    config = SimpleNamespace(
        feishu=SimpleNamespace(
            cli_bin="lark-cli",
            mention_text="@bot",
            bot_open_id="ou_bot",
            bot_app_id="cli_bot",
            seed_chat_id="oc_seed",
            probe_chat_id="oc_probe",
        ),
        openclaw=SimpleNamespace(trajectory_dir=""),
    )
    case = BenchmarkCase(
        case_id="bs001",
        category="long_term_preseed",
        seed_messages=[SeedMessage(id="bs001_s1", content="云帆看板改造项目负责人确定为沈南。")],
        probes=[
            Probe(
                id="bs001_p1",
                question="云帆看板改造项目现在的负责人是谁？",
                gold_answer="负责人是沈南。",
                gold_evidence_ids=["bs001_s1"],
            )
        ],
    )

    adapter = FakeAdapter()
    raw_records = {"feishu": [], "feishu_commands": [], "memory_polls": [], "side_effects": []}
    results = _run_live(
        run_id="run1",
        backend="openclaw-native",
        cases=[case],
        config=config,
        adapter=adapter,
        chats=SimpleNamespace(seed_chat_id="oc_seed", probe_chat_id="oc_probe"),
        judge=FakeJudge(),
        raw_records=raw_records,
        message_interval_seconds=0,
        settle_seconds=0,
        reply_timeout_seconds=1,
        memory_poll_interval_seconds=20,
        memory_timeout_seconds=60,
        yes=True,
    )

    assert sent_messages == [
        ("oc_seed", "云帆看板改造项目负责人确定为沈南。"),
        (
            "oc_seed",
            "@bot 请只基于本群刚刚这组 benchmark seed 对话，整理一份可写入持久记忆的事实摘要。"
            "现在不要声称已经写入文件，也不要编造。"
            "保留项目名、人名、负责人、交付范围、验收人、截止时间、状态更新和明确约束。"
            "摘要末尾单独输出 MEMWING_SEED_FLUSH_READY。",
        ),
        (
            "oc_seed",
            "@bot 现在执行 seed 持久记忆 flush。请把上一条事实摘要和本群 seed 对话中可跨群、跨 session "
            "使用的事实写入 OpenClaw 持久记忆文件 memory/YYYY-MM-DD.md。只基于本群已经出现的消息，"
            "不要编造。写入完成后只回复 MEMWING_SEED_FLUSH_DONE。",
        ),
        ("oc_probe", "@bot 云帆看板改造项目现在的负责人是谁？"),
    ]
    assert adapter.index_count == 1
    assert adapter.search_count == 1
    assert results[0].seed_chat_id == "oc_seed"
    assert results[0].probe_chat_id == "oc_probe"
    assert results[0].durable_memory_available is True
    assert results[0].extraction_timeout is False
    assert [record["kind"] for record in raw_records["feishu"]] == [
        "seed",
        "seed_flush",
        "seed_flush_reply",
        "seed_flush_commit",
        "seed_flush_commit_reply",
        "probe",
        "reply",
    ]
    assert raw_records["memory_polls"][0]["case_id"] == "bs001"


def test_live_run_rejects_same_seed_and_probe_chat(monkeypatch) -> None:
    class FakeFeishu:
        commands = []

        def __init__(self, _bin):
            pass

        def ensure_ready(self, *, required_scopes):
            pass

    monkeypatch.setattr("memwing_benchmark.cli.FeishuCli", FakeFeishu)
    config = SimpleNamespace(
        feishu=SimpleNamespace(cli_bin="lark-cli"),
        openclaw=SimpleNamespace(trajectory_dir=""),
    )

    try:
        _run_live(
            run_id="run1",
            backend="openclaw-native",
            cases=[],
            config=config,
            adapter=SimpleNamespace(commands=[]),
            chats=SimpleNamespace(seed_chat_id="oc_same", probe_chat_id="oc_same"),
            judge=SimpleNamespace(),
            raw_records={
                "feishu": [],
                "feishu_commands": [],
                "memory_polls": [],
                "side_effects": [],
            },
            message_interval_seconds=0,
            settle_seconds=0,
            reply_timeout_seconds=1,
            memory_poll_interval_seconds=20,
            memory_timeout_seconds=60,
            yes=True,
        )
    except BenchmarkError as exc:
        assert "requires different" in str(exc)
    else:
        raise AssertionError("expected BenchmarkError")


def test_prepare_live_chat_creates_seed_and_probe_chats(monkeypatch) -> None:
    created_names = []
    configured_chat_ids = []

    class FakeFeishu:
        commands = []

        def __init__(self, _bin):
            pass

        def ensure_ready(self, *, required_scopes):
            assert required_scopes == ["im:message.send_as_user", "im:chat:create_by_user"]

        def current_app_id(self):
            return "cli_app"

        def create_chat(self, *, name, bot_app_ids):
            created_names.append(name)
            return {"chat_id": f"oc_{len(created_names)}"}

    monkeypatch.setattr("memwing_benchmark.cli.FeishuCli", FakeFeishu)
    config = SimpleNamespace(
        feishu=SimpleNamespace(
            cli_bin="lark-cli",
            chat_id="oc_fixed_default",
            seed_chat_id="oc_fixed_seed",
            probe_chat_id="oc_fixed_probe",
            create_chat_if_missing=True,
            chat_name_prefix="MemWing Bench",
            bot_app_id="bot_app",
        ),
        openclaw=SimpleNamespace(configure_allowlist=False, restart_gateway=False),
    )
    raw_records = {"feishu_commands": [], "side_effects": []}

    chats = _prepare_live_chat(
        config=config,
        adapter=SimpleNamespace(
            configure_feishu_groups=lambda chat_ids, *, require_mention: configured_chat_ids.extend(
                (chat_id, require_mention) for chat_id in chat_ids
            )
        ),
        raw_records=raw_records,
        run_id="run1",
        create_chat=False,
        configure_openclaw=False,
        restart_gateway=False,
        require_mention=True,
        yes=True,
    )

    assert chats.seed_chat_id == "oc_1"
    assert chats.probe_chat_id == "oc_2"
    assert created_names == ["MemWing Bench run1 Seed", "MemWing Bench run1 Probe"]
    assert configured_chat_ids == [("oc_1", True), ("oc_2", True)]
    assert raw_records["side_effects"] == [
        {"action": "create_seed_chat", "chat_id": "oc_1"},
        {"action": "create_probe_chat", "chat_id": "oc_2"},
        {"action": "configure_openclaw", "chat_id": "oc_1", "require_mention": True},
        {"action": "configure_openclaw", "chat_id": "oc_2", "require_mention": True},
    ]


def test_prepare_live_chat_requires_fresh_chat_creation(monkeypatch) -> None:
    class FakeFeishu:
        commands = []

        def __init__(self, _bin):
            pass

        def ensure_ready(self, *, required_scopes):
            raise AssertionError("should fail before checking Feishu readiness")

    monkeypatch.setattr("memwing_benchmark.cli.FeishuCli", FakeFeishu)
    config = SimpleNamespace(
        feishu=SimpleNamespace(
            cli_bin="lark-cli",
            chat_id="oc_fixed_default",
            seed_chat_id="oc_fixed_seed",
            probe_chat_id="oc_fixed_probe",
            create_chat_if_missing=False,
            chat_name_prefix="MemWing Bench",
            bot_app_id="bot_app",
        ),
        openclaw=SimpleNamespace(configure_allowlist=False, restart_gateway=False),
    )

    try:
        _prepare_live_chat(
            config=config,
            adapter=SimpleNamespace(),
            raw_records={"feishu_commands": [], "side_effects": []},
            run_id="run1",
            create_chat=False,
            configure_openclaw=False,
            restart_gateway=False,
            require_mention=True,
            yes=True,
        )
    except BenchmarkError as exc:
        assert "requires fresh seed/probe chats" in str(exc)
    else:
        raise AssertionError("expected BenchmarkError")


def test_live_workspace_uses_one_clean_workspace_per_run(tmp_path: Path) -> None:
    original_workspace = str(tmp_path / "original-openclaw-workspace")
    calls = []

    class FakeAdapter:
        def get_default_workspace(self):
            calls.append(("get", None))
            return original_workspace

        def get_config_value(self, path):
            calls.append(("config_get", path))
            return SimpleNamespace(
                present=True,
                value={"enabled": False, "softThresholdTokens": 6000},
            )

        def set_default_workspace(self, workspace_dir):
            calls.append(("set", str(workspace_dir)))

        def set_config_json(self, path, value):
            calls.append(("config_set", path, value))

        def unset_config_value(self, path):
            calls.append(("config_unset", path))

        def restart_gateway(self):
            calls.append(("restart", None))

    raw_records = {"side_effects": []}
    run_dir = tmp_path / "runs" / "live" / "20260426" / "run1"
    adapter = FakeAdapter()

    restore = _prepare_live_workspace(
        adapter=adapter,
        raw_records=raw_records,
        run_dir=run_dir,
        force_memory_flush=True,
        yes=True,
    )
    _restore_live_workspace(
        adapter=adapter,
        raw_records=raw_records,
        restore=restore,
    )

    workspace = str(run_dir / "openclaw-workspace")
    assert calls == [
        ("get", None),
        ("config_get", "agents.defaults.compaction.memoryFlush"),
        ("set", workspace),
        (
            "config_set",
            "agents.defaults.compaction.memoryFlush",
            {"enabled": True, "softThresholdTokens": 6000, "forceFlushTranscriptBytes": 1},
        ),
        ("restart", None),
        ("set", original_workspace),
        (
            "config_set",
            "agents.defaults.compaction.memoryFlush",
            {"enabled": False, "softThresholdTokens": 6000},
        ),
        ("restart", None),
    ]
    assert raw_records["side_effects"] == [
        {
            "action": "isolate_openclaw_workspace",
            "original_workspace": original_workspace,
            "workspace": workspace,
        },
        {
            "action": "force_openclaw_memory_flush",
            "path": "agents.defaults.compaction.memoryFlush",
            "original_present": True,
        },
        {"action": "restore_openclaw_workspace", "workspace": original_workspace},
        {
            "action": "restore_openclaw_memory_flush",
            "path": "agents.defaults.compaction.memoryFlush",
            "restored_present": True,
        },
    ]


def test_live_workspace_can_skip_forced_memory_flush(tmp_path: Path) -> None:
    calls = []
    original_workspace = str(tmp_path / "original-openclaw-workspace")

    class FakeAdapter:
        def get_default_workspace(self):
            calls.append(("get", None))
            return original_workspace

        def set_default_workspace(self, workspace_dir):
            calls.append(("set", str(workspace_dir)))

        def restart_gateway(self):
            calls.append(("restart", None))

    raw_records = {"side_effects": []}
    run_dir = tmp_path / "runs" / "write" / "20260427" / "run1"

    restore = _prepare_live_workspace(
        adapter=FakeAdapter(),
        raw_records=raw_records,
        run_dir=run_dir,
        force_memory_flush=False,
        yes=True,
    )

    assert restore.memory_flush_touched is False
    assert calls == [
        ("get", None),
        ("set", str(run_dir / "openclaw-workspace")),
        ("restart", None),
    ]
    assert raw_records["side_effects"] == [
        {
            "action": "isolate_openclaw_workspace",
            "original_workspace": original_workspace,
            "workspace": str(run_dir / "openclaw-workspace"),
        }
    ]
