from pathlib import Path

from memwing_benchmark.adapters.openclaw_native import CommandResult, OpenClawNativeAdapter
from memwing_benchmark.schema import BenchmarkCase, CommandRecord, SeedMessage


def test_preseed_exports_seed_messages_without_internal_ids(tmp_path: Path) -> None:
    adapter = OpenClawNativeAdapter(
        Path("/tmp/openclaw"),
        workspace_dir=str(tmp_path),
    )
    commands = []

    def fake_run(args):
        commands.append(args)

    adapter._run = fake_run  # type: ignore[method-assign]
    case = BenchmarkCase(
        case_id="bs001",
        category="long_term_preseed",
        seed_messages=[
            SeedMessage(
                id="bs001_s1",
                time="2026-04-25T09:00:00+08:00",
                sender="周明",
                content="云帆看板改造项目负责人确定为沈南。",
            )
        ],
    )

    path = adapter.preseed_long_term_memories(cases=[case], run_id="run1")

    assert path == tmp_path / "memory" / "memwing-benchmark-preseed.md"
    text = path.read_text(encoding="utf-8")
    assert "云帆看板改造项目负责人确定为沈南。" in text
    assert "2026-04-25T09:00:00+08:00" in text
    assert "bs001_s1" not in text
    assert "[MEM:" not in text
    assert "证据编号" not in text
    assert commands == [["pnpm", "openclaw", "memory", "index", "--force", "--agent", "main"]]


def test_memory_search_returns_context_text(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))

    stdout = '{"items":[{"text":"负责人是沈南"},{"content":"验收时间是 18:00"}]}'
    monkeypatch.setattr(adapter, "_run_full", lambda args: _command_result(args, stdout))

    assert adapter.memory_search("负责人是谁") == ["负责人是沈南", "验收时间是 18:00"]


def test_memory_search_extracts_json_after_pnpm_prefix(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))

    stdout = (
        "> openclaw@2026.4.24 openclaw /tmp/openclaw\n"
        "> node scripts/run-node.mjs memory search --json\n\n"
        '{"results":[{"snippet":"项目负责人是沈南。"}]}'
    )
    monkeypatch.setattr(adapter, "_run_full", lambda args: _command_result(args, stdout))

    assert adapter.memory_search("负责人是谁") == ["项目负责人是沈南。"]


def _command_result(args: list[str], stdout: str) -> CommandResult:
    return CommandResult(
        record=CommandRecord(command=args, cwd="/tmp/openclaw", exit_code=0, stdout=stdout),
        stdout=stdout,
        stderr="",
    )
