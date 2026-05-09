from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from memwing.config_store import ConfigStoreError, default_memwing_home, default_user_config_path, load_effective_config, load_user_config, write_user_config
from memwing.openclaw_installer import build_install_plan, install_openclaw_plugin
from memwing.profiles import build_profile_config
from memwing.runtime_env import build_runtime_env
from memwing.runtime_launcher import _start_runtime_background
from memwing.service_supervisor import render_service_report, verify_profile_services

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
