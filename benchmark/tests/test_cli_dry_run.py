from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from memwing_benchmark.cli import _run_live, app, make_idempotency_key
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
            "cases.json",
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
    sent_texts = []

    class FakeFeishu:
        commands = []

        def __init__(self, _bin):
            pass

        def ensure_ready(self, *, required_scopes):
            assert required_scopes == ["im:message.send_as_user"]

        def send_text(self, *, chat_id, text, idempotency_key):
            sent_texts.append(text)
            return {"message_id": f"msg_{len(sent_texts)}", "chat_id": chat_id}

        def wait_for_bot_reply(self, **_kwargs):
            return {"message_id": "reply_1", "content": "负责人是沈南。"}

    class FakeAdapter:
        commands = []

        def preseed_long_term_memories(self, *, cases, run_id):
            return tmp_path / "memwing-benchmark-preseed.md"

        def memory_search(self, question, *, max_results):
            return ["云帆看板改造项目负责人确定为沈南。"]

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
        ),
        openclaw=SimpleNamespace(trajectory_dir=""),
    )
    case = BenchmarkCase(
        case_id="bs001",
        category="long_term_preseed",
        seed_messages=[
            SeedMessage(id="bs001_s1", content="云帆看板改造项目负责人确定为沈南。")
        ],
        probes=[
            Probe(
                id="bs001_p1",
                question="云帆看板改造项目现在的负责人是谁？",
                gold_answer="负责人是沈南。",
                gold_evidence_ids=["bs001_s1"],
            )
        ],
    )

    _run_live(
        run_id="run1",
        backend="openclaw-native",
        cases=[case],
        config=config,
        adapter=FakeAdapter(),
        chat_id="oc_1",
        judge=FakeJudge(),
        raw_records={"feishu": [], "feishu_commands": [], "side_effects": []},
        message_interval_seconds=0,
        settle_seconds=0,
        reply_timeout_seconds=1,
        yes=True,
    )

    assert sent_texts == [
        "云帆看板改造项目负责人确定为沈南。",
        "@bot 云帆看板改造项目现在的负责人是谁？",
    ]
