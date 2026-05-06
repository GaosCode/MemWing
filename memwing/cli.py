from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from collections.abc import Sequence
from typing import Any

from memwing.config_store import (
    ConfigStoreError,
    default_config,
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
from memwing.runtime_env import build_runtime_env


def main(argv: Sequence[str] | None = None) -> None:
    try:
        raise SystemExit(_run(_parser().parse_args(argv)))
    except ConfigStoreError as exc:
        print(f"memwing: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _run(args: argparse.Namespace) -> int:
    if args.command == "config":
        return _run_config(args)
    if args.command == "start":
        return _run_start(args)
    if args.command == "quickstart":
        return _run_quickstart(args)
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
    return 0


def _run_quickstart(args: argparse.Namespace) -> int:
    profile = args.profile
    if profile != "lite":
        raise ConfigStoreError("quickstart currently supports the lite profile in M1.5")
    path = default_user_config_path()
    config = load_user_config(path)
    merged = default_config()
    _merge(merged, config)
    merged["profile"] = profile
    set_config_value(merged, "runtime.storageBackend", "sqlite")
    set_config_value(merged, "runtime.modelRuntime", "openclaw")
    set_config_value(merged, "graph.backend", "disabled")
    set_config_value(merged, "evidence.backend", "disabled")
    write_user_config(merged, path)

    memwing_home = default_memwing_home()
    for child in ("evidence", "graph", "plugins", "logs"):
        (memwing_home / child).mkdir(parents=True, exist_ok=True)
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
    print("openclaw: install/configure is handled by `memwing openclaw install` in M3")
    return 0


def _apply_flag_overrides(config: dict[str, Any], args: argparse.Namespace) -> None:
    if args.profile is not None:
        set_config_value(config, "profile", args.profile)
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

    start = subcommands.add_parser("start")
    start.add_argument("--profile", choices=("lite", "full-local", "production"))
    start.add_argument("--api-only", action="store_true")
    start.add_argument("--port", type=int)
    start.add_argument("--openclaw-runtime", action="store_true")
    start.add_argument("--print-env", action="store_true")

    quickstart = subcommands.add_parser("quickstart")
    quickstart.add_argument("--profile", choices=("lite", "full-local", "production"), default="lite")
    return parser


if __name__ == "__main__":
    main()
