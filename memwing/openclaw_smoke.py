from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import shlex


PLUGIN_ID = "memwing"


class OpenClawSmokeError(ValueError):
    pass


def verify_runtime_inspect(stdout: str) -> None:
    payload = _parse_json(stdout, "OpenClaw plugin inspect")
    if not isinstance(payload, dict):
        raise OpenClawSmokeError("OpenClaw plugin inspect must return an object")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        raise OpenClawSmokeError("OpenClaw plugin inspect did not include capabilities")
    for entry in capabilities:
        if not isinstance(entry, Mapping):
            continue
        ids = entry.get("ids")
        if entry.get("kind") == "context-engine" and isinstance(ids, list) and PLUGIN_ID in ids:
            return
    plugin = payload.get("plugin")
    if isinstance(plugin, Mapping):
        context_engine_ids = plugin.get("contextEngineIds")
        if isinstance(context_engine_ids, list) and PLUGIN_ID in context_engine_ids:
            return
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, list):
        errors = [
            str(entry.get("message"))
            for entry in diagnostics
            if isinstance(entry, Mapping) and entry.get("level") == "error" and entry.get("message")
        ]
        if errors:
            raise OpenClawSmokeError(
                "OpenClaw runtime did not register the memwing context engine; "
                f"plugin diagnostics: {'; '.join(errors[:3])}"
            )
    raise OpenClawSmokeError("OpenClaw runtime did not register the memwing context engine")


def verify_context_engine(stdout: str) -> None:
    value = json_or_text(stdout)
    if value != PLUGIN_ID:
        raise OpenClawSmokeError(
            f"OpenClaw plugins.slots.contextEngine must be memwing, found {value!r}"
        )


def verify_plugin_entry(stdout: str) -> None:
    value = json_or_text(stdout)
    if not isinstance(value, Mapping):
        raise OpenClawSmokeError("OpenClaw plugins.entries.memwing must be an object")
    if value.get("enabled") is not True:
        raise OpenClawSmokeError("OpenClaw plugins.entries.memwing.enabled must be true")
    hooks = value.get("hooks")
    if not isinstance(hooks, Mapping) or hooks.get("allowConversationAccess") is not True:
        raise OpenClawSmokeError(
            "OpenClaw plugins.entries.memwing.hooks.allowConversationAccess must be true"
        )


def render_status_text(
    *,
    inspect_stdout: str,
    slot_stdout: str,
    entry_stdout: str,
    inspect_argv: Sequence[str],
) -> str:
    verify_runtime_inspect(inspect_stdout)
    verify_context_engine(slot_stdout)
    verify_plugin_entry(entry_stdout)
    return "\n".join(
        (
            "plugin: memwing",
            "runtime: ok",
            f"contextEngine: {json_or_text(slot_stdout)}",
            "enabled: true",
            "conversationHook: true",
            f"inspect_command: {' '.join(shlex.quote(part) for part in inspect_argv)}",
        )
    )


def json_or_text(stdout: str) -> object:
    text = stdout.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _parse_json(stdout: str, label: str) -> object:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise OpenClawSmokeError(f"{label} did not return JSON") from exc
