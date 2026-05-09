from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

from memwing.config_store import ConfigStoreError, default_memwing_home, default_user_config_path, load_effective_config, set_config_value
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


def _apply_profile_override(config: dict[str, object], args: argparse.Namespace) -> None:
    if getattr(args, "profile", None) is not None:
        set_config_value(config, "profile", args.profile)

def _run_restart(args: argparse.Namespace) -> int:
    config = load_effective_config()
    _apply_profile_override(config, args)
    runtime_env = build_runtime_env(config)
    memwing_home = default_memwing_home()
    if runtime_env.profile == "full-local" and not args.skip_service_check:
        report = verify_profile_services(config)
        print(f"profile: {runtime_env.profile}")
        print(f"config: {default_user_config_path()}")
        print(render_service_report(report))
        if not report.ok:
            return 1
    else:
        print(f"profile: {runtime_env.profile}")
        print(f"config: {default_user_config_path()}")

    stop_message = _stop_runtime_from_pid_file(memwing_home)
    print(stop_message)
    launch = _start_runtime_background(
        runtime_env,
        memwing_home,
        startup_timeout_seconds=args.startup_timeout_seconds,
    )
    print(f"runtime: started pid={launch.pid}")
    print("runtime: healthy")
    print(f"runtime_log: {launch.log_path}")
    return 0

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

def _stop_runtime_from_pid_file(memwing_home: Path) -> str:
    pid_path = memwing_home / "runtime.pid"
    if not pid_path.exists():
        return "runtime: no existing pid file"
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_path.unlink(missing_ok=True)
        return "runtime: removed invalid pid file"

    command = _process_command(pid)
    if command is None:
        pid_path.unlink(missing_ok=True)
        return f"runtime: removed stale pid file pid={pid}"
    if "memwing.runtime_runner" not in command:
        pid_path.unlink(missing_ok=True)
        return f"runtime: removed stale pid file pid={pid} command={command}"

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + FAILED_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _process_command(pid) is None:
            pid_path.unlink(missing_ok=True)
            return f"runtime: stopped pid={pid}"
        time.sleep(0.05)
    os.kill(pid, signal.SIGKILL)
    pid_path.unlink(missing_ok=True)
    return f"runtime: killed pid={pid}"

def _process_command(pid: int) -> str | None:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    command = completed.stdout.strip()
    return command or None

def _runtime_health_url(env: dict[str, str]) -> str:
    host = env["MEMWING_API_HOST"]
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{env['MEMWING_API_PORT']}/healthz"

def _runtime_startup_grace_seconds(timeout_seconds: float) -> float:
    return min(DEFAULT_RUNTIME_STARTUP_GRACE_SECONDS, max(0.0, timeout_seconds))
