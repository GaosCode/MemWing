from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from memwing.config_store import (
    ConfigStoreError,
    default_memwing_home,
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
    build_install_plan,
    install_openclaw_plugin,
    openclaw_status,
    render_install_dry_run,
    render_status_text as render_openclaw_status_text,
)
from memwing.profiles import build_profile_config
from memwing.runtime_env import build_runtime_env
from memwing.service_supervisor import render_service_report, verify_profile_services


DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS = 15.0
DEFAULT_RUNTIME_STARTUP_GRACE_SECONDS = 1.0
RUNTIME_HEALTH_POLL_SECONDS = 0.05
FAILED_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class RuntimeLaunch:
    pid: int
    log_path: Path
    pid_path: Path


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
    if args.command == "config":
        return _run_config(args)
    if args.command == "start":
        return _run_start(args)
    if args.command == "quickstart":
        return _run_quickstart(args)
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


def _run_quickstart(args: argparse.Namespace) -> int:
    profile = args.profile
    if profile == "production":
        raise ConfigStoreError("use `memwing setup --profile production` for production config")
    path = default_user_config_path()
    config = load_user_config(path)
    merged = build_profile_config(profile, config)
    if args.dry_run:
        _print_quickstart_dry_run(profile, path, merged)
        return 0
    write_user_config(merged, path)

    memwing_home = default_memwing_home()
    for child in ("evidence", "graph", "plugins", "logs"):
        (memwing_home / child).mkdir(parents=True, exist_ok=True)
    if profile == "full-local":
        report = verify_profile_services(load_effective_config())
        print(f"profile: {profile}")
        print(f"config: {path}")
        print(render_service_report(report))
        if report.ok:
            _finish_quickstart(args, load_effective_config(), memwing_home)
        return 0 if report.ok else 1

    sqlite_path = Path(
        build_runtime_env(load_effective_config()).env["MEMWING_LITE_DB_PATH"]
    ).expanduser()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    from memwing.infrastructure.db.sqlite_store import SQLiteDataStore

    SQLiteDataStore.from_path(sqlite_path)
    print(f"profile: {profile}")
    print(f"config: {path}")
    print(f"state: {sqlite_path}")
    print("graph: disabled")
    print("evidence: disabled")
    _finish_quickstart(args, load_effective_config(), memwing_home)
    return 0


def _print_quickstart_dry_run(profile: str, path: Path, config: dict[str, Any]) -> None:
    print(f"profile: {profile}")
    print("mode: dry-run")
    print(f"would_write_config: {path}")
    runtime_env = build_runtime_env(config)
    if profile == "lite":
        print(f"would_create_state: {runtime_env.env['MEMWING_LITE_DB_PATH']}")
        print("graph: disabled")
        print("evidence: disabled")
    else:
        print("would_verify: postgres qdrant neo4j")
    print("openclaw: would install packaged plugin and configure OpenClaw")
    print("runtime: would start memwing-runtime in the background")


def _finish_quickstart(args: argparse.Namespace, config: dict[str, Any], memwing_home: Path) -> None:
    if args.skip_openclaw:
        print("openclaw: skipped")
    else:
        plan = build_install_plan(config)
        install_openclaw_plugin(plan, smoke=not args.skip_smoke)
        print(f"openclaw: installed {plan.plugin_dir}")
        if not args.skip_smoke:
            print("openclaw_smoke: ok")

    if args.no_start:
        print("runtime: skipped")
    else:
        launch = _start_runtime_background(
            build_runtime_env(config),
            memwing_home,
            startup_timeout_seconds=args.startup_timeout_seconds,
        )
        print(f"runtime: started pid={launch.pid}")
        print("runtime: healthy")
        print(f"runtime_log: {launch.log_path}")


def _start_runtime_background(
    runtime_env: object,
    memwing_home: Path,
    *,
    startup_timeout_seconds: float = DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS,
) -> RuntimeLaunch:
    env = getattr(runtime_env, "env")
    logs_dir = memwing_home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "runtime.log"
    pid_path = memwing_home / "runtime.pid"
    startup_grace_seconds = _runtime_startup_grace_seconds(startup_timeout_seconds)
    log_handle = log_path.open("ab")
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memwing.runtime_runner",
                "--host",
                env["MEMWING_API_HOST"],
                "--port",
                env["MEMWING_API_PORT"],
                "--startup-grace-seconds",
                f"{startup_grace_seconds:g}",
            ],
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    try:
        _wait_for_runtime_health(
            process,
            _runtime_health_url(env),
            timeout_seconds=startup_timeout_seconds,
            startup_grace_seconds=startup_grace_seconds,
            log_path=log_path,
        )
    except BaseException:
        _cleanup_failed_runtime_start(process, pid_path)
        raise
    return RuntimeLaunch(pid=process.pid, log_path=log_path, pid_path=pid_path)


def _wait_for_runtime_health(
    process: object,
    health_url: str,
    *,
    timeout_seconds: float,
    startup_grace_seconds: float,
    log_path: Path,
) -> None:
    if timeout_seconds <= 0:
        raise ConfigStoreError("startup timeout must be greater than 0 seconds")
    deadline = time.monotonic() + timeout_seconds
    healthy = False
    healthy_after = 0.0
    last_error: BaseException | None = None

    while True:
        exit_code = process.poll()
        if exit_code is not None:
            raise ConfigStoreError(
                f"MemWing runtime exited before becoming healthy "
                f"(exit code {exit_code}); see {log_path}"
            )

        now = time.monotonic()
        if healthy and now >= healthy_after:
            return
        if now >= deadline:
            break

        if not healthy:
            try:
                response = urlopen(
                    health_url,
                    timeout=min(1.0, max(RUNTIME_HEALTH_POLL_SECONDS, deadline - now)),
                )
                close = getattr(response, "close", None)
                if callable(close):
                    close()
                healthy = True
                healthy_after = min(deadline, now + startup_grace_seconds)
            except (OSError, TimeoutError, URLError) as exc:
                last_error = exc

        time.sleep(min(RUNTIME_HEALTH_POLL_SECONDS, max(0.0, deadline - now)))

    _terminate_runtime_process(process)
    detail = f"; last health error: {last_error}" if last_error is not None else ""
    raise ConfigStoreError(
        f"MemWing runtime did not become healthy within {timeout_seconds:g}s; "
        f"see {log_path}{detail}"
    )


def _terminate_runtime_process(process: object) -> None:
    terminate = getattr(process, "terminate", None)
    if callable(terminate) and process.poll() is None:
        terminate()
    wait = getattr(process, "wait", None)
    if callable(wait):
        try:
            wait(timeout=FAILED_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            kill = getattr(process, "kill", None)
            if callable(kill):
                kill()
                wait(timeout=FAILED_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS)
        except TypeError:
            wait()


def _cleanup_failed_runtime_start(process: object, pid_path: Path) -> None:
    _terminate_runtime_process(process)
    try:
        pid_path.unlink()
    except FileNotFoundError:
        pass


def _runtime_health_url(env: dict[str, str]) -> str:
    host = env["MEMWING_API_HOST"]
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{env['MEMWING_API_PORT']}/healthz"


def _runtime_startup_grace_seconds(timeout_seconds: float) -> float:
    return min(DEFAULT_RUNTIME_STARTUP_GRACE_SECONDS, max(0.0, timeout_seconds))


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
        inspect, slot, entry = openclaw_status(plan)
        print(render_openclaw_status_text(inspect, slot, entry))
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


def _apply_profile_override(config: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "profile", None) is not None:
        set_config_value(config, "profile", args.profile)


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
