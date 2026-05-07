from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
from typing import Any

from memwing.config_store import ConfigStoreError, default_memwing_home, get_config_value
from memwing.openclaw_smoke import (
    OpenClawSmokeError,
    PLUGIN_ID,
    render_status_text as render_smoke_status_text,
    verify_context_engine,
    verify_plugin_entry,
    verify_runtime_inspect,
)


class OpenClawInstallerError(ConfigStoreError):
    pass


@dataclass(frozen=True, slots=True)
class OpenClawCommand:
    argv: tuple[str, ...]
    cwd: str | None = None

    def display(self) -> str:
        return " ".join(shlex.quote(part) for part in self.argv)


@dataclass(frozen=True, slots=True)
class OpenClawCommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class OpenClawInstallPlan:
    plugin_dir: Path
    plugin_source_dir: Path
    memwing_base_url: str
    workspace_id: str
    project_memory_space_id: str
    openclaw_command: str
    openclaw_args: tuple[str, ...]
    openclaw_cwd: str | None = None

    def plugin_install_command(self) -> OpenClawCommand:
        return self._command("plugins", "install", "--link", str(self.plugin_dir))

    def config_set_command(self) -> OpenClawCommand:
        return self._command("config", "set", "--batch-json", self.batch_json())

    def runtime_inspect_command(self) -> OpenClawCommand:
        return self._command("plugins", "inspect", PLUGIN_ID, "--runtime", "--json")

    def context_engine_command(self) -> OpenClawCommand:
        return self._command("config", "get", "plugins.slots.contextEngine", "--json")

    def memory_slot_command(self) -> OpenClawCommand:
        return self._command("config", "get", "plugins.slots.memory", "--json")

    def plugin_entry_command(self) -> OpenClawCommand:
        return self._command("config", "get", "plugins.entries.memwing", "--json")

    def batch_entries(self) -> tuple[dict[str, object], ...]:
        return (
            {"path": "plugins.entries.memwing.enabled", "value": True},
            {
                "path": "plugins.entries.memwing.hooks.allowConversationAccess",
                "value": True,
            },
            {
                "path": "plugins.entries.memwing.config",
                "value": {
                    "memwingBaseUrl": self.memwing_base_url,
                    "workspaceId": self.workspace_id,
                    "nativeMemoryTools": True,
                    "defaultScope": {
                        "project_memory_space_id": self.project_memory_space_id,
                    },
                },
            },
            {"path": "plugins.slots.contextEngine", "value": PLUGIN_ID},
            {"path": "plugins.slots.memory", "value": PLUGIN_ID},
        )

    def batch_json(self) -> str:
        return json.dumps(self.batch_entries(), separators=(",", ":"), sort_keys=True)

    def commands(self, *, include_smoke: bool = True) -> tuple[OpenClawCommand, ...]:
        commands = (self.plugin_install_command(), self.config_set_command())
        if include_smoke:
            commands += (
                self.runtime_inspect_command(),
                self.context_engine_command(),
                self.memory_slot_command(),
                self.plugin_entry_command(),
            )
        return commands

    def _command(self, *args: str) -> OpenClawCommand:
        return OpenClawCommand(
            argv=(self.openclaw_command, *self.openclaw_args, *args),
            cwd=self.openclaw_cwd,
        )


def build_install_plan(
    config: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    plugin_dir: Path | None = None,
    base_url: str | None = None,
    workspace_id: str | None = None,
    project_memory_space_id: str | None = None,
    openclaw_cli: str | None = None,
    validate_plugin: bool = True,
) -> OpenClawInstallPlan:
    source = os.environ if env is None else env
    command, command_args, cwd = _openclaw_command(config, env=source, override=openclaw_cli)
    resolved_plugin_source_dir = (
        (plugin_dir or default_plugin_dir(env=source)).resolve() if validate_plugin else Path(".").resolve()
    )
    if validate_plugin:
        _validate_plugin_dir(resolved_plugin_source_dir)
    resolved_plugin_dir = (
        _managed_plugin_dir(env=source).resolve() if validate_plugin else resolved_plugin_source_dir
    )
    return OpenClawInstallPlan(
        plugin_dir=resolved_plugin_dir,
        plugin_source_dir=resolved_plugin_source_dir,
        memwing_base_url=(
            _nonempty(base_url)
            or _optional_config(config, "openclaw.memwingBaseUrl")
            or _base_url_from_config(config)
        ),
        workspace_id=(
            _nonempty(workspace_id)
            or _optional_config(config, "openclaw.workspaceId")
            or "workspace_001"
        ),
        project_memory_space_id=(
            _nonempty(project_memory_space_id)
            or _optional_config(config, "scope.defaultProject")
            or "project_001"
        ),
        openclaw_command=command,
        openclaw_args=command_args,
        openclaw_cwd=cwd,
    )


def render_install_dry_run(plan: OpenClawInstallPlan, *, include_smoke: bool = True) -> str:
    lines = [
        f"plugin_source_dir: {plan.plugin_source_dir}",
        f"plugin_dir: {plan.plugin_dir}",
        f"memwingBaseUrl: {plan.memwing_base_url}",
        f"workspaceId: {plan.workspace_id}",
        f"project_memory_space_id: {plan.project_memory_space_id}",
        "commands:",
    ]
    lines.extend(f"  {command.display()}" for command in plan.commands(include_smoke=include_smoke))
    lines.append("batch_json:")
    lines.append(plan.batch_json())
    return "\n".join(lines)


def install_openclaw_plugin(
    plan: OpenClawInstallPlan,
    *,
    runner: CommandRunner | None = None,
    smoke: bool = True,
) -> tuple[OpenClawCommandResult, ...]:
    command_runner = runner or run_command
    _copy_plugin_artifact(plan.plugin_source_dir, plan.plugin_dir)
    results: list[OpenClawCommandResult] = []
    for command in (plan.plugin_install_command(), plan.config_set_command()):
        results.append(_run_checked(command_runner, command))
    if smoke:
        inspect = _run_checked(command_runner, plan.runtime_inspect_command())
        context_slot = _run_checked(command_runner, plan.context_engine_command())
        memory_slot = _run_checked(command_runner, plan.memory_slot_command())
        entry = _run_checked(command_runner, plan.plugin_entry_command())
        _verify_smoke(inspect.stdout, context_slot.stdout, memory_slot.stdout, entry.stdout)
        results.extend((inspect, context_slot, memory_slot, entry))
    return tuple(results)


def openclaw_status(
    plan: OpenClawInstallPlan,
    *,
    runner: CommandRunner | None = None,
) -> tuple[
    OpenClawCommandResult,
    OpenClawCommandResult,
    OpenClawCommandResult,
    OpenClawCommandResult,
]:
    command_runner = runner or run_command
    inspect = _run_checked(command_runner, plan.runtime_inspect_command())
    context_slot = _run_checked(command_runner, plan.context_engine_command())
    memory_slot = _run_checked(command_runner, plan.memory_slot_command())
    entry = _run_checked(command_runner, plan.plugin_entry_command())
    _verify_smoke(inspect.stdout, context_slot.stdout, memory_slot.stdout, entry.stdout)
    return inspect, context_slot, memory_slot, entry


def render_status_text(
    inspect: OpenClawCommandResult,
    context_slot: OpenClawCommandResult,
    memory_slot: OpenClawCommandResult,
    entry: OpenClawCommandResult,
) -> str:
    return render_smoke_status_text(
        inspect_stdout=inspect.stdout,
        context_slot_stdout=context_slot.stdout,
        memory_slot_stdout=memory_slot.stdout,
        entry_stdout=entry.stdout,
        inspect_argv=inspect.argv,
    )


def default_plugin_dir(
    *,
    env: Mapping[str, str] | None = None,
    module_file: Path | None = None,
) -> Path:
    source = os.environ if env is None else env
    configured = source.get("MEMWING_OPENCLAW_PLUGIN_DIR")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())

    module_path = Path(__file__).resolve() if module_file is None else module_file.resolve()
    for parent in module_path.parents:
        candidates.append(parent / "memwing-openclaw-plugin")
    candidates.append(module_path.parent / "integrations" / "openclaw")

    for candidate in candidates:
        if (candidate / "openclaw.plugin.json").exists():
            return candidate
    raise OpenClawInstallerError(
        "OpenClaw plugin artifact not found; set MEMWING_OPENCLAW_PLUGIN_DIR."
    )


CommandRunner = Callable[[OpenClawCommand], OpenClawCommandResult]


def run_command(command: OpenClawCommand) -> OpenClawCommandResult:
    completed = subprocess.run(
        command.argv,
        cwd=command.cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    return OpenClawCommandResult(
        argv=command.argv,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_checked(runner: CommandRunner, command: OpenClawCommand) -> OpenClawCommandResult:
    result = runner(command)
    if result.returncode != 0:
        raise OpenClawInstallerError(
            f"OpenClaw command failed: {command.display()}\n{result.stdout}{result.stderr}"
        )
    return result


def _validate_plugin_dir(plugin_dir: Path) -> None:
    manifest = plugin_dir / "openclaw.plugin.json"
    if not manifest.exists():
        raise OpenClawInstallerError(f"OpenClaw plugin manifest is missing: {manifest}")
    dist_manifest = plugin_dir / "dist" / "openclaw.plugin.json"
    if not dist_manifest.exists():
        raise OpenClawInstallerError(f"OpenClaw plugin dist manifest is missing: {dist_manifest}")
    entrypoint = plugin_dir / "dist" / "index.js"
    if not entrypoint.exists():
        raise OpenClawInstallerError(f"OpenClaw plugin dist/index.js is missing: {entrypoint}")


def _copy_plugin_artifact(source_dir: Path, target_dir: Path) -> None:
    if source_dir.resolve() == target_dir.resolve():
        return
    _validate_plugin_dir(source_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
    _validate_plugin_dir(target_dir)


def _managed_plugin_dir(*, env: Mapping[str, str]) -> Path:
    configured = _nonempty(env.get("MEMWING_OPENCLAW_MANAGED_PLUGIN_DIR"))
    if configured is not None:
        return Path(configured).expanduser()
    return default_memwing_home(env) / "plugins" / "openclaw" / "memwing" / _memwing_version(env)


def _memwing_version(env: Mapping[str, str]) -> str:
    configured = _nonempty(env.get("MEMWING_VERSION"))
    if configured is not None:
        return configured
    try:
        return version("memwing")
    except PackageNotFoundError:
        return "0.1.0-dev"


def _verify_smoke(
    inspect_stdout: str,
    context_slot_stdout: str,
    memory_slot_stdout: str,
    entry_stdout: str,
) -> None:
    try:
        verify_runtime_inspect(inspect_stdout)
        verify_context_engine(context_slot_stdout)
        verify_context_engine(memory_slot_stdout, label="plugins.slots.memory")
        verify_plugin_entry(entry_stdout)
    except OpenClawSmokeError as exc:
        raise OpenClawInstallerError(str(exc)) from exc


def _openclaw_command(
    config: Mapping[str, Any],
    *,
    env: Mapping[str, str],
    override: str | None,
) -> tuple[str, tuple[str, ...], str | None]:
    command = (
        _nonempty(override)
        or _optional_config(config, "openclaw.cli")
        or _nonempty(env.get("OPENCLAW_CLI"))
        or "openclaw"
    )
    raw_args = _optional_config(config, "openclaw.cliArgs") or _nonempty(
        env.get("OPENCLAW_CLI_ARGS")
    ) or ""
    cwd = _optional_config(config, "openclaw.cwd") or _nonempty(env.get("OPENCLAW_CLI_CWD"))
    return command, tuple(shlex.split(raw_args)), cwd


def _base_url_from_config(config: Mapping[str, Any]) -> str:
    host = _optional_config(config, "api.host") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = _optional_config(config, "api.port") or "8000"
    return f"http://{host}:{port}"


def _optional_config(config: Mapping[str, Any], dotted_key: str) -> str | None:
    try:
        value = get_config_value(config, dotted_key)
    except ValueError:
        return None
    return _nonempty(value)


def _nonempty(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
