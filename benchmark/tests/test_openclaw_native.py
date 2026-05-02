import json
from pathlib import Path

from memwing_benchmark.adapters.openclaw_native import CommandResult, OpenClawNativeAdapter
from memwing_benchmark.schema import BenchmarkCase, CommandRecord, SeedMessage


def test_preseed_exports_full_seed_messages_without_internal_ids(tmp_path: Path) -> None:
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
    assert text == ("2026-04-25T09:00:00+08:00 周明：云帆看板改造项目负责人确定为沈南。\n")
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


def test_memory_search_details_preserves_openclaw_scores(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))

    stdout = (
        '{"results":[{"path":"memory/2026-04-26.md","startLine":1,"endLine":5,'
        '"score":0.57,"vectorScore":0.82,"textScore":0,'
        '"snippet":"负责人是沈南","source":"memory"}]}'
    )
    monkeypatch.setattr(adapter, "_run_full", lambda args: _command_result(args, stdout))

    details = adapter.memory_search_details("负责人是谁")

    assert details.contexts == ["负责人是沈南"]
    assert details.latency_ms >= 0
    assert details.results[0]["rank"] == 1
    assert details.results[0]["path"] == "memory/2026-04-26.md"
    assert details.results[0]["score"] == 0.57
    assert details.results[0]["vectorScore"] == 0.82
    assert details.results[0]["textScore"] == 0.0


def test_memory_search_extracts_json_after_pnpm_prefix(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))

    stdout = (
        "> openclaw@2026.4.24 openclaw /tmp/openclaw\n"
        "> node scripts/run-node.mjs memory search --json\n\n"
        '{"results":[{"snippet":"项目负责人是沈南。"}]}'
    )
    monkeypatch.setattr(adapter, "_run_full", lambda args: _command_result(args, stdout))

    assert adapter.memory_search("负责人是谁") == ["项目负责人是沈南。"]


def test_parses_pretty_json_after_pnpm_prefix(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))
    stdout = (
        "> openclaw@2026.4.24 openclaw /tmp/openclaw\n"
        "> node scripts/run-node.mjs memory search --json\n\n"
        "[\n"
        "  {\n"
        '    "status": {\n'
        '      "workspaceDir": "/tmp/openclaw-workspace"\n'
        "    }\n"
        "  }\n"
        "]\n"
    )
    monkeypatch.setattr(adapter, "_run", lambda args: _command_record(args, stdout))

    assert adapter.resolve_workspace() == Path("/tmp/openclaw-workspace")


def test_configure_feishu_group_preserves_allowlist_with_pnpm_prefix(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))
    commands = []

    def fake_run_full(args):
        commands.append(args)
        if args[:5] == [
            "pnpm",
            "openclaw",
            "config",
            "get",
            "channels.feishu.groupAllowFrom",
        ]:
            return _command_result(
                args,
                (
                    "> openclaw@2026.4.24 openclaw /tmp/openclaw\n"
                    "> node scripts/run-node.mjs config get channels.feishu.groupAllowFrom --json\n\n"
                    '["oc_existing"]'
                ),
            )
        return _command_result(args, "{}")

    monkeypatch.setattr(adapter, "_run_full", fake_run_full)

    adapter.configure_feishu_group("oc_new")

    allowlist_set = [
        args
        for args in commands
        if args[:5] == ["pnpm", "openclaw", "config", "set", "channels.feishu.groupAllowFrom"]
    ]
    assert json.loads(allowlist_set[0][5]) == ["oc_existing", "oc_new"]


def test_configure_feishu_groups_writes_allowlist_once(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))
    commands = []

    def fake_run_full(args):
        commands.append(args)
        if args[:5] == [
            "pnpm",
            "openclaw",
            "config",
            "get",
            "channels.feishu.groupAllowFrom",
        ]:
            return _command_result(args, '["oc_existing"]')
        return _command_result(args, "{}")

    monkeypatch.setattr(adapter, "_run_full", fake_run_full)

    adapter.configure_feishu_groups(["oc_seed", "oc_probe"])

    allowlist_set = [
        args
        for args in commands
        if args[:5] == ["pnpm", "openclaw", "config", "set", "channels.feishu.groupAllowFrom"]
    ]
    require_mention_sets = [
        args
        for args in commands
        if args[:4] == ["pnpm", "openclaw", "config", "set"] and "requireMention" in args[4]
    ]
    assert len(allowlist_set) == 1
    assert json.loads(allowlist_set[0][5]) == ["oc_existing", "oc_seed", "oc_probe"]
    assert [args[4] for args in require_mention_sets] == [
        "channels.feishu.groups.oc_seed.requireMention",
        "channels.feishu.groups.oc_probe.requireMention",
    ]
    assert [args[5] for args in require_mention_sets] == ["true", "true"]


def test_configure_feishu_groups_can_disable_require_mention(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))
    commands = []

    def fake_run_full(args):
        commands.append(args)
        if args[:5] == [
            "pnpm",
            "openclaw",
            "config",
            "get",
            "channels.feishu.groupAllowFrom",
        ]:
            return _command_result(args, "[]")
        return _command_result(args, "{}")

    monkeypatch.setattr(adapter, "_run_full", fake_run_full)

    adapter.configure_feishu_groups(["oc_seed"], require_mention=False)

    require_mention_sets = [
        args
        for args in commands
        if args[:4] == ["pnpm", "openclaw", "config", "set"] and "requireMention" in args[4]
    ]
    assert require_mention_sets[0][4] == "channels.feishu.groups.oc_seed.requireMention"
    assert require_mention_sets[0][5] == "false"


def test_get_default_workspace_parses_json_string_with_pnpm_prefix(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))
    stdout = (
        "> openclaw@2026.4.24 openclaw /tmp/openclaw\n"
        "> node scripts/run-node.mjs config get agents.defaults.workspace --json\n\n"
        '"/tmp/openclaw-workspace"'
    )
    monkeypatch.setattr(adapter, "_run_full", lambda args: _command_result(args, stdout))

    assert adapter.get_default_workspace() == "/tmp/openclaw-workspace"


def test_resolve_workspace_parses_memory_status_with_pnpm_prefix(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))
    stdout = (
        "> openclaw@2026.4.24 openclaw /tmp/openclaw\n"
        "> node scripts/run-node.mjs memory status --deep --json --agent main\n\n"
        '[{"agentId":"main","status":{"workspaceDir":"/tmp/openclaw-workspace"}}]'
    )
    monkeypatch.setattr(adapter, "_run", lambda args: _command_record(args, stdout))

    assert adapter.resolve_workspace() == Path("/tmp/openclaw-workspace")


def test_get_config_value_handles_missing_path(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))

    def fake_run_full(args, *, allow_not_found=False):
        assert allow_not_found is True
        return CommandResult(
            record=CommandRecord(
                command=args,
                cwd="/tmp/openclaw",
                exit_code=1,
                stdout="",
                stderr="Config path not found: agents.defaults.compaction.memoryFlush",
            ),
            stdout="",
            stderr="Config path not found: agents.defaults.compaction.memoryFlush",
        )

    monkeypatch.setattr(adapter, "_run_full", fake_run_full)

    value = adapter.get_config_value("agents.defaults.compaction.memoryFlush")

    assert value.present is False
    assert value.value is None


def test_get_config_value_parses_boolean_with_pnpm_prefix(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))
    stdout = (
        "> openclaw@2026.4.30 openclaw /tmp/openclaw\n"
        "> node scripts/run-node.mjs config get plugins.entries.memwing.enabled --json\n\n"
        "true\n"
    )
    monkeypatch.setattr(adapter, "_run_full", lambda args, **kwargs: _command_result(args, stdout))

    value = adapter.get_config_value("plugins.entries.memwing.enabled")

    assert value.present is True
    assert value.value is True


def test_set_and_unset_config_value_use_strict_json(monkeypatch) -> None:
    adapter = OpenClawNativeAdapter(Path("/tmp/openclaw"))
    commands = []

    def fake_run(args):
        commands.append(args)

    monkeypatch.setattr(adapter, "_run", fake_run)

    adapter.set_config_json("agents.defaults.compaction.memoryFlush", {"enabled": True})
    adapter.unset_config_value("agents.defaults.compaction.memoryFlush")

    assert commands[0][:5] == [
        "pnpm",
        "openclaw",
        "config",
        "set",
        "agents.defaults.compaction.memoryFlush",
    ]
    assert json.loads(commands[0][5]) == {"enabled": True}
    assert commands[0][6] == "--strict-json"
    assert commands[1] == [
        "pnpm",
        "openclaw",
        "config",
        "unset",
        "agents.defaults.compaction.memoryFlush",
    ]


def _command_result(args: list[str], stdout: str) -> CommandResult:
    return CommandResult(
        record=CommandRecord(command=args, cwd="/tmp/openclaw", exit_code=0, stdout=stdout),
        stdout=stdout,
        stderr="",
    )


def _command_record(args: list[str], stdout: str) -> CommandRecord:
    return CommandRecord(command=args, cwd="/tmp/openclaw", exit_code=0, stdout=stdout)
