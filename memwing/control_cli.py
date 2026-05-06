from __future__ import annotations

from collections.abc import Mapping, Sequence
import argparse
import json
import uuid
from typing import Any

from memwing.control_client import ControlClient
from memwing.runtime_env import build_runtime_env


class ControlCliError(ValueError):
    pass


READ_COMMANDS = {
    ("memories", "list"): ("GET", "/v1/control/memories"),
    ("memories", "show"): ("GET", "/v1/control/memories/{memory_id}"),
    ("sources", "list"): ("GET", "/v1/control/source-events"),
    ("pages", "list"): ("GET", "/v1/control/pages"),
    ("push", "list"): ("GET", "/v1/control/maintenance"),
}

MUTATION_COMMANDS = {
    ("memories", "approve"): ("POST", "/v1/memory/{memory_id}/approve"),
    ("memories", "archive"): ("POST", "/v1/memory/{memory_id}/archive"),
    ("sources", "purge"): ("POST", "/v1/source-events/{source_event_id}/purge"),
    ("push", "send"): (
        "POST",
        "/v1/platforms/{platform}/push-candidates/{candidate_id}/send",
    ),
}


def run_control_command(args: argparse.Namespace, config: Mapping[str, Any]) -> int:
    key = (args.control_resource, args.control_action)
    if key in READ_COMMANDS:
        return _run_read(args, config, *READ_COMMANDS[key])
    if key in MUTATION_COMMANDS:
        return _run_mutation(args, config, *MUTATION_COMMANDS[key])
    raise ControlCliError("control command is required")


def add_control_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    control = subcommands.add_parser("control")
    control.add_argument("--base-url")
    resources = control.add_subparsers(dest="control_resource", required=True)

    memories = resources.add_parser("memories")
    memory_actions = memories.add_subparsers(dest="control_action", required=True)
    memory_list = memory_actions.add_parser("list")
    _add_read_options(memory_list)
    memory_show = memory_actions.add_parser("show")
    memory_show.add_argument("memory_id")
    _add_read_options(memory_show)
    memory_approve = memory_actions.add_parser("approve")
    memory_approve.add_argument("memory_id")
    _add_mutation_options(memory_approve)
    memory_archive = memory_actions.add_parser("archive")
    memory_archive.add_argument("memory_id")
    _add_mutation_options(memory_archive)

    sources = resources.add_parser("sources")
    source_actions = sources.add_subparsers(dest="control_action", required=True)
    source_list = source_actions.add_parser("list")
    _add_read_options(source_list)
    source_purge = source_actions.add_parser("purge")
    source_purge.add_argument("source_event_id")
    source_purge.add_argument(
        "--purge-level",
        choices=("memwing_redaction",),
        default="memwing_redaction",
    )
    _add_mutation_options(source_purge)

    pages = resources.add_parser("pages")
    page_actions = pages.add_subparsers(dest="control_action", required=True)
    page_list = page_actions.add_parser("list")
    _add_read_options(page_list)

    push = resources.add_parser("push")
    push_actions = push.add_subparsers(dest="control_action", required=True)
    push_list = push_actions.add_parser("list")
    _add_read_options(push_list)
    push_send = push_actions.add_parser("send")
    push_send.add_argument("candidate_id")
    push_send.add_argument("--platform", required=True)
    _add_mutation_options(push_send)


def _run_read(
    args: argparse.Namespace,
    config: Mapping[str, Any],
    method: str,
    path_template: str,
) -> int:
    payload = _client(args, config).request(
        method,
        _path(path_template, args),
        params=_query(args),
    )
    print(_format_payload(payload, as_json=args.json))
    return 0


def _run_mutation(
    args: argparse.Namespace,
    config: Mapping[str, Any],
    method: str,
    path_template: str,
) -> int:
    path = _path(path_template, args)
    params = _query(args)
    body = _mutation_body(args)
    if not args.yes:
        print(_mutation_preview(method, path, params, body))
        answer = input("Proceed? [y/N] ").strip().casefold()
        if answer not in ("y", "yes"):
            print("aborted")
            return 1
    payload = _client(args, config).request(method, path, params=params, json_body=body)
    print(_format_payload(payload, as_json=args.json))
    return 0


def _add_read_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--cursor")


def _add_mutation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--actor-id", default="memwing-cli")
    parser.add_argument("--reason")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")


def _client(args: argparse.Namespace, config: Mapping[str, Any]) -> ControlClient:
    return ControlClient(args.base_url or _base_url(config))


def _base_url(config: Mapping[str, Any]) -> str:
    runtime_env = build_runtime_env(config).env
    host = runtime_env.get("MEMWING_API_HOST", "127.0.0.1")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = runtime_env.get("MEMWING_API_PORT", "8000")
    return f"http://{host}:{port}"


def _query(args: argparse.Namespace) -> dict[str, str]:
    params = {"project_memory_space_id": args.project}
    if getattr(args, "limit", None) is not None:
        params["limit"] = str(args.limit)
    if getattr(args, "cursor", None):
        params["cursor"] = args.cursor
    return params


def _path(path_template: str, args: argparse.Namespace) -> str:
    values = {
        "memory_id": getattr(args, "memory_id", None),
        "source_event_id": getattr(args, "source_event_id", None),
        "candidate_id": getattr(args, "candidate_id", None),
        "platform": getattr(args, "platform", None),
    }
    try:
        return path_template.format(**values)
    except KeyError as exc:
        raise ControlCliError(f"missing control path value: {exc}") from exc


def _mutation_body(args: argparse.Namespace) -> dict[str, object]:
    reason = args.reason or _default_reason(args)
    body: dict[str, object] = {
        "actor_id": args.actor_id,
        "reason": reason,
        "idempotency_key": f"memwing-cli:{uuid.uuid4()}",
    }
    purge_level = getattr(args, "purge_level", None)
    if purge_level is not None:
        body["purge_level"] = purge_level
    return body


def _default_reason(args: argparse.Namespace) -> str:
    subject = (
        getattr(args, "memory_id", None)
        or getattr(args, "source_event_id", None)
        or getattr(args, "candidate_id", None)
        or "unknown"
    )
    return f"memwing control {args.control_resource} {args.control_action} {subject}"


def _mutation_preview(
    method: str,
    path: str,
    params: Mapping[str, str],
    body: Mapping[str, object],
) -> str:
    project = params["project_memory_space_id"]
    return "\n".join(
        (
            "Control Plane mutation preview:",
            f"method: {method}",
            f"path: {path}",
            f"project: {project}",
            f"actor_id: {body['actor_id']}",
            f"reason: {body['reason']}",
        )
    )


def _format_payload(payload: Mapping[str, Any], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    items = _items(payload)
    if items is not None:
        return _format_table(items)
    return _format_detail(payload)


def _items(payload: Mapping[str, Any]) -> Sequence[Mapping[str, Any]] | None:
    for key in ("items", "push_candidates"):
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return tuple(item for item in value if isinstance(item, Mapping))
    return None


def _format_table(items: Sequence[Mapping[str, Any]]) -> str:
    if not items:
        return "(empty)"
    columns = _columns(items)
    widths = {
        column: max(len(column), *(len(_cell(item.get(column))) for item in items))
        for column in columns
    }
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    separator = "  ".join("-" * widths[column] for column in columns)
    rows = [
        "  ".join(_cell(item.get(column)).ljust(widths[column]) for column in columns)
        for item in items
    ]
    return "\n".join((header, separator, *rows))


def _columns(items: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    preferred = (
        "memory_id",
        "source_event_id",
        "page_id",
        "candidate_id",
        "title",
        "status",
        "lifecycle_status",
        "platform",
        "updated_at",
    )
    discovered: list[str] = []
    for column in preferred:
        if any(column in item for item in items):
            discovered.append(column)
    if discovered:
        return tuple(discovered)
    return tuple(str(key) for key in items[0].keys())


def _format_detail(payload: Mapping[str, Any]) -> str:
    return "\n".join(f"{key}: {_cell(value)}" for key, value in payload.items())


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)
