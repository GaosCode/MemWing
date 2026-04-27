from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from memwing_benchmark.adapters.openclaw_native import MemorySearchDetails
from memwing_benchmark.cli import (
    _prepare_live_chat,
    _prepare_live_workspace,
    _restore_live_workspace,
    _run_offline_batch,
    _run_live,
    app,
    make_idempotency_key,
)
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.evaluators.llm_judge import (
    AnswerJudgeBlock,
    JudgeResult,
    RetrievalJudgeBlock,
)
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
    mode_dir = tmp_path / "offline"
    assert mode_dir.exists()
    day_dirs = list(mode_dir.iterdir())
    assert len(day_dirs) == 1
    run_dirs = list(day_dirs[0].iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "normalized.jsonl").exists()
    assert (run_dirs[0] / "scores.json").exists()
    assert (run_dirs[0] / "report.md").exists()


def test_cli_rejects_live_batch_mode() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--live", "--batch"])

    assert result.exit_code == 1
    assert "--batch currently supports offline retrieval runs only" in result.output


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
            configure_feishu_groups=lambda chat_ids: configured_chat_ids.extend(chat_ids)
        ),
        raw_records=raw_records,
        run_id="run1",
        create_chat=False,
        configure_openclaw=False,
        restart_gateway=False,
        yes=True,
    )

    assert chats.seed_chat_id == "oc_1"
    assert chats.probe_chat_id == "oc_2"
    assert created_names == ["MemWing Bench run1 Seed", "MemWing Bench run1 Probe"]
    assert configured_chat_ids == ["oc_1", "oc_2"]
    assert raw_records["side_effects"] == [
        {"action": "create_seed_chat", "chat_id": "oc_1"},
        {"action": "create_probe_chat", "chat_id": "oc_2"},
        {"action": "configure_openclaw", "chat_id": "oc_1"},
        {"action": "configure_openclaw", "chat_id": "oc_2"},
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
