from __future__ import annotations

import json
from pathlib import Path

import pytest

from memwing.config_store import default_config, set_config_value
from memwing.openclaw_installer import (
    OpenClawCommand,
    OpenClawCommandResult,
    OpenClawInstallerError,
    apply_repair_plan,
    build_install_plan,
    build_repair_plan,
    default_plugin_dir,
    install_openclaw_plugin,
    render_install_dry_run,
    render_repair_plan,
)


def test_openclaw_install_dry_run_prints_exact_writes(tmp_path: Path) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    config = default_config()
    set_config_value(config, "api.port", 8123)

    plan = build_install_plan(
        config,
        env={"OPENCLAW_CLI": "pnpm", "OPENCLAW_CLI_ARGS": "openclaw"},
        plugin_dir=plugin_dir,
        workspace_id="workspace_custom",
        project_memory_space_id="project_custom",
    )
    rendered = render_install_dry_run(plan)

    assert "pnpm openclaw plugins install --link" in rendered
    assert "pnpm openclaw config set --batch-json" in rendered
    assert "plugins.entries.memwing.hooks.allowConversationAccess" in rendered
    assert "plugins.slots.contextEngine" in rendered
    assert "plugins.slots.memory" in rendered
    batch = _batch_from_plan(plan)
    assert batch[2]["value"] == {
        "memwingBaseUrl": "http://127.0.0.1:8123",
        "workspaceId": "workspace_custom",
        "nativeMemoryTools": True,
        "defaultScope": {"project_memory_space_id": "project_custom"},
    }


def test_openclaw_install_uses_link_batch_json_and_smoke(tmp_path: Path) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    config = default_config()
    memwing_home = tmp_path / "home"
    plan = build_install_plan(
        config,
        env={"MEMWING_HOME": str(memwing_home), "MEMWING_VERSION": "1.2.3"},
        plugin_dir=plugin_dir,
        base_url="http://memwing",
    )
    calls: list[OpenClawCommand] = []

    def runner(command: OpenClawCommand) -> OpenClawCommandResult:
        calls.append(command)
        if command.argv[1:3] == ("plugins", "inspect"):
            stdout = json.dumps(
                {
                    "capabilities": [
                        {"kind": "context-engine", "ids": ["memwing"]},
                        {"kind": "memory", "ids": ["memwing"]},
                    ]
                }
            )
        elif command.argv[1:3] == ("config", "get"):
            if command.argv[3] in ("plugins.slots.contextEngine", "plugins.slots.memory"):
                stdout = json.dumps("memwing")
            else:
                stdout = json.dumps(
                    {
                        "enabled": True,
                        "hooks": {"allowConversationAccess": True},
                        "config": {"nativeMemoryTools": True},
                    }
                )
        else:
            stdout = ""
        return OpenClawCommandResult(command.argv, 0, stdout, "")

    results = install_openclaw_plugin(plan, runner=runner)

    managed_plugin = memwing_home / "plugins" / "openclaw" / "memwing" / "1.2.3"
    assert results[-3].stdout == '"memwing"'
    assert results[-2].stdout == '"memwing"'
    assert json.loads(results[-1].stdout)["enabled"] is True
    assert plan.plugin_source_dir == plugin_dir.resolve()
    assert plan.plugin_dir == managed_plugin.resolve()
    assert (managed_plugin / "openclaw.plugin.json").exists()
    assert calls[0].argv == ("openclaw", "plugins", "install", "--link", str(managed_plugin.resolve()))
    assert calls[1].argv[:4] == ("openclaw", "config", "set", "--batch-json")
    assert _batch_from_command(calls[1])[0] == {
        "path": "plugins.entries.memwing.enabled",
        "value": True,
    }
    assert calls[2].argv == ("openclaw", "plugins", "inspect", "memwing", "--runtime", "--json")
    assert calls[3].argv == ("openclaw", "config", "get", "plugins.slots.contextEngine", "--json")
    assert calls[4].argv == ("openclaw", "config", "get", "plugins.slots.memory", "--json")
    assert calls[5].argv == ("openclaw", "config", "get", "plugins.entries.memwing", "--json")


def test_openclaw_install_fails_when_smoke_does_not_register_context_engine(
    tmp_path: Path,
) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    plan = build_install_plan(default_config(), env={}, plugin_dir=plugin_dir)

    def runner(command: OpenClawCommand) -> OpenClawCommandResult:
        if command.argv[1:3] == ("plugins", "inspect"):
            return OpenClawCommandResult(command.argv, 0, '{"capabilities":[]}', "")
        if command.argv[1:3] == ("config", "get"):
            if command.argv[3] in ("plugins.slots.contextEngine", "plugins.slots.memory"):
                return OpenClawCommandResult(command.argv, 0, '"memwing"', "")
            return OpenClawCommandResult(
                command.argv,
                0,
                '{"enabled":true,"hooks":{"allowConversationAccess":true},"config":{"nativeMemoryTools":true}}',
                "",
            )
        return OpenClawCommandResult(command.argv, 0, "", "")

    with pytest.raises(OpenClawInstallerError, match="context engine"):
        install_openclaw_plugin(plan, runner=runner)


def test_openclaw_install_fails_when_conversation_hook_is_disabled(
    tmp_path: Path,
) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    plan = build_install_plan(default_config(), env={}, plugin_dir=plugin_dir)

    def runner(command: OpenClawCommand) -> OpenClawCommandResult:
        if command.argv[1:3] == ("plugins", "inspect"):
            return OpenClawCommandResult(
                command.argv,
                0,
                '{"capabilities":[{"kind":"context-engine","ids":["memwing"]}]}',
                "",
            )
        if command.argv[1:3] == ("config", "get"):
            if command.argv[3] in ("plugins.slots.contextEngine", "plugins.slots.memory"):
                return OpenClawCommandResult(command.argv, 0, '"memwing"', "")
            return OpenClawCommandResult(
                command.argv,
                0,
                '{"enabled":true,"hooks":{"allowConversationAccess":false},"config":{"nativeMemoryTools":true}}',
                "",
            )
        return OpenClawCommandResult(command.argv, 0, "", "")

    with pytest.raises(OpenClawInstallerError, match="allowConversationAccess"):
        install_openclaw_plugin(plan, runner=runner)


def test_default_plugin_dir_prefers_packaged_release_artifact(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    packaged_plugin = release_root / "memwing-openclaw-plugin"
    _write_plugin_artifact(packaged_plugin)
    module_file = release_root / "lib" / "python" / "memwing" / "openclaw_installer.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")

    assert default_plugin_dir(env={}, module_file=module_file) == packaged_plugin


def test_default_plugin_dir_can_be_overridden_by_env(tmp_path: Path) -> None:
    plugin_dir = _plugin_artifact(tmp_path)

    assert default_plugin_dir(env={"MEMWING_OPENCLAW_PLUGIN_DIR": str(plugin_dir)}) == plugin_dir


def test_openclaw_plugin_validation_requires_manifest_and_entrypoint(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "dist").mkdir(parents=True)
    (plugin_dir / "openclaw.plugin.json").write_text('{"id":"memwing"}', encoding="utf-8")
    (plugin_dir / "dist" / "openclaw.plugin.json").write_text(
        '{"id":"memwing"}',
        encoding="utf-8",
    )

    with pytest.raises(OpenClawInstallerError, match="dist/index.js"):
        build_install_plan(default_config(), env={}, plugin_dir=plugin_dir)


def test_openclaw_dry_run_reports_managed_plugin_target(tmp_path: Path) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    memwing_home = tmp_path / "home"

    plan = build_install_plan(
        default_config(),
        env={"MEMWING_HOME": str(memwing_home), "MEMWING_VERSION": "1.2.3"},
        plugin_dir=plugin_dir,
    )

    rendered = render_install_dry_run(plan)

    assert f"plugin_source_dir: {plugin_dir.resolve()}" in rendered
    assert f"plugin_dir: {(memwing_home / 'plugins/openclaw/memwing/1.2.3').resolve()}" in rendered


def test_openclaw_install_plan_treats_blank_cli_env_as_unset(tmp_path: Path) -> None:
    plugin_dir = _plugin_artifact(tmp_path)

    plan = build_install_plan(
        default_config(),
        env={
            "OPENCLAW_CLI": "",
            "OPENCLAW_CLI_ARGS": "",
            "OPENCLAW_CLI_CWD": "",
        },
        plugin_dir=plugin_dir,
    )

    command = plan.plugin_install_command()
    assert command.argv[0] == "openclaw"
    assert command.cwd is None


def test_openclaw_repair_plan_removes_stale_memwing_managed_paths(tmp_path: Path) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    memwing_home = tmp_path / "home"
    current_managed = memwing_home / "plugins" / "openclaw" / "memwing" / "1.2.3"
    stale_managed = memwing_home / "plugins" / "openclaw" / "memwing" / "1.2.2"
    other_plugin = tmp_path / "other-plugin"
    current_managed.mkdir(parents=True)
    _write_plugin_artifact(stale_managed)
    other_plugin.mkdir()
    openclaw_config = tmp_path / "openclaw.json"
    openclaw_config.write_text(
        json.dumps(
            {
                "plugins": {
                    "load": {
                        "paths": [
                            str(stale_managed),
                            str(other_plugin),
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    plan = build_repair_plan(
        default_config(),
        env={"MEMWING_HOME": str(memwing_home), "MEMWING_VERSION": "1.2.3"},
        plugin_dir=plugin_dir,
        config_path=openclaw_config,
    )

    assert plan.removed_paths == (str(stale_managed),)
    assert plan.added_paths == (str(current_managed.resolve()),)
    assert plan.repaired_paths == (str(other_plugin), str(current_managed.resolve()))
    rendered = render_repair_plan(plan)
    assert "memwing openclaw repair --yes" in rendered
    assert "openclaw config set plugins.load.paths" in rendered


def test_openclaw_repair_plan_applies_backup_and_registry_refresh(tmp_path: Path) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    memwing_home = tmp_path / "home"
    current_managed = memwing_home / "plugins" / "openclaw" / "memwing" / "1.2.3"
    stale_managed = memwing_home / "plugins" / "openclaw" / "memwing" / "1.2.2"
    current_managed.mkdir(parents=True)
    _write_plugin_artifact(stale_managed)
    openclaw_config = tmp_path / "openclaw.json"
    openclaw_config.write_text(
        json.dumps({"plugins": {"load": {"paths": [str(stale_managed)]}}}),
        encoding="utf-8",
    )
    installs_path = tmp_path / "plugins" / "installs.json"
    installs_path.parent.mkdir()
    installs_path.write_text(
        json.dumps(
            {
                "installRecords": {
                    "memwing": {
                        "sourcePath": str(stale_managed),
                        "installPath": str(stale_managed),
                    },
                    "other": {"sourcePath": str(tmp_path / "other")},
                }
            }
        ),
        encoding="utf-8",
    )
    plan = build_repair_plan(
        default_config(),
        env={"MEMWING_HOME": str(memwing_home), "MEMWING_VERSION": "1.2.3"},
        plugin_dir=plugin_dir,
        config_path=openclaw_config,
    )
    assert plan.remove_install_record is True
    calls: list[OpenClawCommand] = []

    def runner(command: OpenClawCommand) -> OpenClawCommandResult:
        calls.append(command)
        return OpenClawCommandResult(command.argv, 0, "", "")

    backup_paths, _result = apply_repair_plan(plan, runner=runner)

    assert len(backup_paths) == 2
    assert all(path.exists() for path in backup_paths)
    assert json.loads(openclaw_config.read_text())["plugins"]["load"]["paths"] == [
        str(current_managed.resolve())
    ]
    install_records = json.loads(installs_path.read_text())["installRecords"]
    assert "memwing" not in install_records
    assert "other" in install_records
    assert calls[0].argv == ("openclaw", "plugins", "registry", "--refresh")


def test_openclaw_command_failure_suggests_memwing_repair_for_config_schema_errors(
    tmp_path: Path,
) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    plan = build_install_plan(default_config(), env={}, plugin_dir=plugin_dir)

    def runner(command: OpenClawCommand) -> OpenClawCommandResult:
        return OpenClawCommandResult(
            command.argv,
            1,
            "",
            "Config invalid\nProblem:\n  - plugins: plugin manifest requires configSchema\n",
        )

    with pytest.raises(OpenClawInstallerError, match="memwing openclaw repair"):
        install_openclaw_plugin(plan, runner=runner)


def _plugin_artifact(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "plugin"
    _write_plugin_artifact(plugin_dir)
    return plugin_dir


def _write_plugin_artifact(plugin_dir: Path) -> None:
    (plugin_dir / "dist").mkdir(parents=True)
    (plugin_dir / "openclaw.plugin.json").write_text('{"id":"memwing"}', encoding="utf-8")
    (plugin_dir / "dist" / "openclaw.plugin.json").write_text(
        '{"id":"memwing"}',
        encoding="utf-8",
    )
    (plugin_dir / "dist" / "index.js").write_text("module.exports = {}", encoding="utf-8")


def _batch_from_plan(plan) -> list[dict[str, object]]:
    return json.loads(plan.batch_json())


def _batch_from_command(command: OpenClawCommand) -> list[dict[str, object]]:
    return json.loads(command.argv[4])
