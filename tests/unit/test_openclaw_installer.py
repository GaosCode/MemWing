from __future__ import annotations

import json
from pathlib import Path

import pytest

from memwing.config_store import default_config, set_config_value
from memwing.openclaw_installer import (
    OpenClawCommand,
    OpenClawCommandResult,
    OpenClawInstallerError,
    build_install_plan,
    default_plugin_dir,
    install_openclaw_plugin,
    render_install_dry_run,
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
    batch = _batch_from_plan(plan)
    assert batch[2]["value"] == {
        "memwingBaseUrl": "http://127.0.0.1:8123",
        "workspaceId": "workspace_custom",
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
                    ]
                }
            )
        elif command.argv[1:3] == ("config", "get"):
            if command.argv[3] == "plugins.slots.contextEngine":
                stdout = json.dumps("memwing")
            else:
                stdout = json.dumps(
                    {"enabled": True, "hooks": {"allowConversationAccess": True}}
                )
        else:
            stdout = ""
        return OpenClawCommandResult(command.argv, 0, stdout, "")

    results = install_openclaw_plugin(plan, runner=runner)

    managed_plugin = memwing_home / "plugins" / "openclaw" / "memwing" / "1.2.3"
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
    assert calls[4].argv == ("openclaw", "config", "get", "plugins.entries.memwing", "--json")


def test_openclaw_install_fails_when_smoke_does_not_register_context_engine(
    tmp_path: Path,
) -> None:
    plugin_dir = _plugin_artifact(tmp_path)
    plan = build_install_plan(default_config(), env={}, plugin_dir=plugin_dir)

    def runner(command: OpenClawCommand) -> OpenClawCommandResult:
        if command.argv[1:3] == ("plugins", "inspect"):
            return OpenClawCommandResult(command.argv, 0, '{"capabilities":[]}', "")
        if command.argv[1:3] == ("config", "get"):
            if command.argv[3] == "plugins.slots.contextEngine":
                return OpenClawCommandResult(command.argv, 0, '"memwing"', "")
            return OpenClawCommandResult(
                command.argv,
                0,
                '{"enabled":true,"hooks":{"allowConversationAccess":true}}',
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
            if command.argv[3] == "plugins.slots.contextEngine":
                return OpenClawCommandResult(command.argv, 0, '"memwing"', "")
            return OpenClawCommandResult(
                command.argv,
                0,
                '{"enabled":true,"hooks":{"allowConversationAccess":false}}',
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
