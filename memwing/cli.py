from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from collections.abc import Sequence
from typing import Any
from urllib.request import urlopen

from memwing.config_store import (
    ConfigStoreError,
    default_user_config_path,
    get_config_value,
    load_effective_config,
    load_user_config,
    parse_config_value,
    set_config_value,
    unset_config_value,
    write_user_config,
)
from memwing.control_client import ControlClientError
from memwing.control_cli import ControlCliError, add_control_parser, run_control_command
from memwing.control_plane_launcher import (
    ControlPlaneLauncherError,
    DEFAULT_CONTROL_PLANE_HOST,
    DEFAULT_CONTROL_PLANE_PORT,
    run_control_plane_command,
)
from memwing.doctor import (
    build_runtime_status,
    dumps_report_json,
    render_doctor_text,
    render_status_text,
    run_doctor,
)
from memwing.openclaw_installer import (
    OpenClawInstallerError,
    apply_repair_plan,
    build_install_plan,
    build_repair_plan,
    install_openclaw_plugin,
    openclaw_status,
    render_install_dry_run,
    render_repair_plan,
    render_status_text as render_openclaw_status_text,
)
from memwing.profiles import build_profile_config
from memwing.runtime_env import build_runtime_env
from memwing import quickstart_cli as _quickstart_cli
from memwing import runtime_launcher as _runtime_launcher
from memwing.quickstart_cli import _run_quickstart
from memwing.runtime_launcher import (
    DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS,
    RuntimeLaunch,
    _apply_profile_override,
    _run_restart,
    _start_runtime_background,
    _stop_runtime_from_pid_file,
)
from memwing.service_supervisor import render_service_report, verify_profile_services


__all__ = [
    "RuntimeLaunch",
    "_start_runtime_background",
    "_stop_runtime_from_pid_file",
    "install_openclaw_plugin",
    "main",
    "subprocess",
    "urlopen",
    "verify_profile_services",
]


def main(argv: Sequence[str] | None = None) -> None:
    try:
        raise SystemExit(_run(_parser().parse_args(argv)))
    except (
        ConfigStoreError,
        ControlCliError,
        ControlClientError,
        ControlPlaneLauncherError,
        OpenClawInstallerError,
    ) as exc:
        print(f"memwing: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _run(args: argparse.Namespace) -> int:
    _sync_split_cli_dependencies()
    if args.command == "config":
        return _run_config(args)
    if args.command == "scope":
        return _run_scope(args)
    if args.command == "start":
        return _run_start(args)
    if args.command == "quickstart":
        return _run_quickstart(args)
    if args.command == "restart":
        return _run_restart(args)
    if args.command == "setup":
        return _run_setup(args)
    if args.command == "doctor":
        return _run_doctor(args)
    if args.command == "status":
        return _run_status(args)
    if args.command == "openclaw":
        return _run_openclaw(args)
    if args.command == "control":
        return _run_control(args)
    if args.command == "control-plane":
        return _run_control_plane(args)
    raise ConfigStoreError("command is required")


def _sync_split_cli_dependencies() -> None:
    _quickstart_cli.install_openclaw_plugin = install_openclaw_plugin
    _quickstart_cli.render_service_report = render_service_report
    _quickstart_cli.verify_profile_services = verify_profile_services
    _quickstart_cli._start_runtime_background = _start_runtime_background
    _runtime_launcher.subprocess = subprocess
    _runtime_launcher.urlopen = urlopen
    _runtime_launcher._start_runtime_background = _start_runtime_background
    _runtime_launcher._stop_runtime_from_pid_file = _stop_runtime_from_pid_file


def _run_config(args: argparse.Namespace) -> int:
    path = default_user_config_path()
    config = load_user_config(path)
    if args.config_command == "file":
        print(path)
        return 0
    if args.config_command == "get":
        effective = load_effective_config()
        value = get_config_value(effective, args.key)
        print(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
        return 0
    if args.config_command == "set":
        set_config_value(config, args.key, parse_config_value(args.value))
        write_user_config(config, path)
        print(f"updated {path}")
        return 0
    if args.config_command == "unset":
        unset_config_value(config, args.key)
        write_user_config(config, path)
        print(f"updated {path}")
        return 0
    raise ConfigStoreError("config command is required")


def _run_scope(args: argparse.Namespace) -> int:
    if args.scope_command == "create":
        return _run_scope_create(args)
    raise ConfigStoreError("scope command is required")


def _run_scope_create(args: argparse.Namespace) -> int:
    scope_id = _scope_id(args.scope_id)
    workspace_id = _scope_workspace_id(args.workspace_id, load_effective_config())
    config_path = default_user_config_path()
    config = load_user_config(config_path)
    if args.use:
        set_config_value(config, "scope.defaultProject", scope_id)
        if args.workspace_id is not None:
            set_config_value(config, "openclaw.workspaceId", workspace_id)
        write_user_config(config, config_path)

    effective_config = load_effective_config()
    _ensure_scope_storage(effective_config, scope_id, workspace_id)
    print(f"scope: {scope_id}")
    print(f"storage: seeded runtime binding for workspace {workspace_id}")
    if args.use:
        print(f"config: updated {config_path}")
    else:
        print("config: unchanged")

    if args.openclaw:
        plan = build_install_plan(
            effective_config,
            plugin_dir=args.plugin_dir,
            workspace_id=workspace_id,
            project_memory_space_id=scope_id,
            openclaw_cli=args.openclaw_cli,
        )
        install_openclaw_plugin(plan, smoke=not args.skip_smoke)
        print(f"openclaw: configured {plan.plugin_dir}")
        if not args.skip_smoke:
            print("openclaw_smoke: ok")
    else:
        print("openclaw: skipped")

    print("restart: run `memwing quickstart --skip-openclaw` and `openclaw gateway restart` to apply")
    return 0


def _scope_id(raw_scope_id: str | None) -> str:
    if raw_scope_id is not None and raw_scope_id.strip():
        return raw_scope_id.strip()
    return f"demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _scope_workspace_id(raw_workspace_id: str | None, config: dict[str, Any]) -> str:
    if raw_workspace_id is not None and raw_workspace_id.strip():
        return raw_workspace_id.strip()
    value = get_config_value(config, "openclaw.workspaceId")
    text = str(value).strip()
    return text or "workspace_001"


def _ensure_scope_storage(config: dict[str, Any], scope_id: str, workspace_id: str) -> None:
    runtime_env = build_runtime_env(config)
    env = dict(runtime_env.env)
    env["MEMWING_DEFAULT_PROJECT_MEMORY_SPACE_ID"] = scope_id
    env["MEMWING_OPENCLAW_WORKSPACE_ID"] = workspace_id
    with _patched_environ(env):
        if env.get("MEMWING_STORAGE_BACKEND") == "sqlite":
            sqlite_path = Path(env["MEMWING_LITE_DB_PATH"]).expanduser()
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            from memwing.bootstrap_scope import ensure_lite_scope
            from memwing.infrastructure.db.sqlite_store import SQLiteDataStore

            store = SQLiteDataStore.from_path(sqlite_path)
            asyncio.run(ensure_lite_scope(store))
            return

        database_url = env.get("DATABASE_URL")
        if not database_url:
            raise ConfigStoreError("database.url is required to create a scope for this profile")
        asyncio.run(_ensure_postgres_scope(database_url))


async def _ensure_postgres_scope(database_url: str) -> None:
    from memwing.bootstrap_scope import ensure_postgres_scope
    from memwing.infrastructure.db.postgres_connection import PooledPostgresConnection

    connection = await PooledPostgresConnection.connect(database_url, min_size=1, max_size=1)
    try:
        await ensure_postgres_scope(connection)
    finally:
        await connection.close()


@contextmanager
def _patched_environ(env: dict[str, str]) -> object:
    previous = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env)
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def _run_start(args: argparse.Namespace) -> int:
    config = load_effective_config()
    _apply_flag_overrides(config, args)
    runtime_env = build_runtime_env(config)
    if args.print_env:
        print(json.dumps(runtime_env.redacted(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    previous_env = dict(os.environ)
    try:
        os.environ.update(runtime_env.env)
        from memwing.runtime_runner import main as runtime_main

        runtime_args = [
            "--host",
            runtime_env.env["MEMWING_API_HOST"],
            "--port",
            runtime_env.env["MEMWING_API_PORT"],
        ]
        if args.api_only:
            runtime_args.append("--api-only")
        runtime_main(runtime_args)
    finally:
        os.environ.clear()
        os.environ.update(previous_env)
    return 0


def _run_setup(args: argparse.Namespace) -> int:
    if args.profile != "production":
        raise ConfigStoreError("setup currently supports the production profile")
    path = default_user_config_path()
    config = build_profile_config(args.profile, load_user_config(path))
    write_user_config(config, path)
    print(f"profile: {args.profile}")
    print(f"config: {path}")
    print("infrastructure: externally managed")
    print("provisioning: skipped")
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    config = load_effective_config()
    _apply_profile_override(config, args)
    report = run_doctor(config, fix=args.fix)
    print(dumps_report_json(report) if args.json else render_doctor_text(report))
    return report.exit_code()


def _run_status(args: argparse.Namespace) -> int:
    config = load_effective_config()
    _apply_profile_override(config, args)
    status = build_runtime_status(
        config,
        config_path=str(default_user_config_path()),
        check_health=not args.no_health,
    )
    print(dumps_report_json(status) if args.json else render_status_text(status))
    return 0


def _run_openclaw(args: argparse.Namespace) -> int:
    config = load_effective_config()
    if args.openclaw_command == "install":
        plan = build_install_plan(
            config,
            plugin_dir=args.plugin_dir,
            base_url=args.base_url,
            workspace_id=args.workspace_id,
            project_memory_space_id=args.project_memory_space_id,
            openclaw_cli=args.openclaw_cli,
        )
        if args.dry_run:
            print(render_install_dry_run(plan, include_smoke=not args.skip_smoke))
            return 0
        install_openclaw_plugin(plan, smoke=not args.skip_smoke)
        print(f"installed: {plan.plugin_dir}")
        print(f"configured: {plan.memwing_base_url}")
        if not args.skip_smoke:
            print("smoke: ok")
        return 0
    if args.openclaw_command == "status":
        plan = build_install_plan(config, openclaw_cli=args.openclaw_cli, validate_plugin=False)
        inspect, context_slot, memory_slot, entry = openclaw_status(plan)
        print(render_openclaw_status_text(inspect, context_slot, memory_slot, entry))
        return 0
    if args.openclaw_command == "repair":
        plan = build_repair_plan(
            config,
            plugin_dir=args.plugin_dir,
            openclaw_cli=args.openclaw_cli,
        )
        print(render_repair_plan(plan))
        if not args.yes:
            return 0
        backup_paths, _result = apply_repair_plan(plan)
        for backup_path in backup_paths:
            print(f"backup: {backup_path}")
        print("repair: applied")
        print("registry: refreshed")
        return 0
    raise ConfigStoreError("openclaw command is required")


def _run_control(args: argparse.Namespace) -> int:
    config = load_effective_config()
    return run_control_command(args, config)


def _run_control_plane(args: argparse.Namespace) -> int:
    config = load_effective_config()
    return run_control_plane_command(args, config)


def _apply_flag_overrides(config: dict[str, Any], args: argparse.Namespace) -> None:
    _apply_profile_override(config, args)
    if args.port is not None:
        set_config_value(config, "api.port", args.port)
    if args.openclaw_runtime:
        set_config_value(config, "runtime.modelRuntime", "openclaw")


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(target.get(key), dict) and isinstance(value, dict):
            _merge(target[key], value)
        else:
            target[key] = value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memwing")
    subcommands = parser.add_subparsers(dest="command", required=True)

    config = subcommands.add_parser("config")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("file")
    get = config_commands.add_parser("get")
    get.add_argument("key")
    set_cmd = config_commands.add_parser("set")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")
    unset = config_commands.add_parser("unset")
    unset.add_argument("key")

    scope = subcommands.add_parser("scope")
    scope_commands = scope.add_subparsers(dest="scope_command", required=True)
    scope_create = scope_commands.add_parser("create")
    scope_create.add_argument("scope_id", nargs="?")
    scope_create.add_argument("--use", action="store_true")
    scope_create.add_argument("--openclaw", action="store_true")
    scope_create.add_argument("--skip-smoke", action="store_true")
    scope_create.add_argument("--workspace-id")
    scope_create.add_argument("--plugin-dir", type=Path)
    scope_create.add_argument("--openclaw-cli")

    start = subcommands.add_parser("start")
    start.add_argument("--profile", choices=("lite", "full-local", "production"))
    start.add_argument("--api-only", action="store_true")
    start.add_argument("--port", type=int)
    start.add_argument("--openclaw-runtime", action="store_true")
    start.add_argument("--print-env", action="store_true")

    quickstart = subcommands.add_parser("quickstart")
    quickstart.add_argument("--profile", choices=("lite", "full-local", "production"), default="lite")
    quickstart.add_argument("--dry-run", action="store_true")
    quickstart.add_argument("--skip-openclaw", action="store_true")
    quickstart.add_argument("--skip-smoke", action="store_true")
    quickstart.add_argument("--no-start", action="store_true")
    quickstart.add_argument(
        "--startup-timeout-seconds",
        type=float,
        default=DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS,
    )

    restart = subcommands.add_parser("restart")
    restart.add_argument("--profile", choices=("lite", "full-local", "production"))
    restart.add_argument("--skip-service-check", action="store_true")
    restart.add_argument(
        "--startup-timeout-seconds",
        type=float,
        default=DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS,
    )

    setup = subcommands.add_parser("setup")
    setup.add_argument("--profile", choices=("production",), required=True)

    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--profile", choices=("lite", "full-local", "production"))
    doctor.add_argument("--fix", action="store_true")
    doctor.add_argument("--json", action="store_true")

    status = subcommands.add_parser("status")
    status.add_argument("--profile", choices=("lite", "full-local", "production"))
    status.add_argument("--json", action="store_true")
    status.add_argument("--no-health", action="store_true")

    openclaw = subcommands.add_parser("openclaw")
    openclaw_commands = openclaw.add_subparsers(dest="openclaw_command", required=True)
    openclaw_install = openclaw_commands.add_parser("install")
    openclaw_install.add_argument("--dry-run", action="store_true")
    openclaw_install.add_argument("--skip-smoke", action="store_true")
    openclaw_install.add_argument("--base-url")
    openclaw_install.add_argument("--workspace-id")
    openclaw_install.add_argument("--project-memory-space-id")
    openclaw_install.add_argument("--plugin-dir", type=Path)
    openclaw_install.add_argument("--openclaw-cli")
    openclaw_status_cmd = openclaw_commands.add_parser("status")
    openclaw_status_cmd.add_argument("--openclaw-cli")
    openclaw_repair = openclaw_commands.add_parser("repair")
    openclaw_repair.add_argument("--yes", action="store_true")
    openclaw_repair.add_argument("--plugin-dir", type=Path)
    openclaw_repair.add_argument("--openclaw-cli")

    control_plane = subcommands.add_parser("control-plane")
    control_plane.add_argument("--open", action="store_true")
    control_plane.add_argument("--host", default=DEFAULT_CONTROL_PLANE_HOST)
    control_plane.add_argument("--port", type=int, default=DEFAULT_CONTROL_PLANE_PORT)
    control_plane.add_argument("--api-base-url")
    control_plane.add_argument("--mock", action="store_true")

    add_control_parser(subcommands)
    return parser


if __name__ == "__main__":
    main()
