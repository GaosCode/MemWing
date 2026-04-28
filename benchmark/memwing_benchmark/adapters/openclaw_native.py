from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, NamedTuple

from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.json_utils import dumps_json, loads_json, walk_values
from memwing_benchmark.metrics.retrieval import unique_preserve_order
from memwing_benchmark.schema import BenchmarkCase, CommandRecord, SeedMessage


class CommandResult(NamedTuple):
    record: CommandRecord
    stdout: str
    stderr: str


class ConfigValue(NamedTuple):
    present: bool
    value: Any = None


class MemorySearchDetails(NamedTuple):
    contexts: list[str]
    results: list[dict[str, Any]]
    latency_ms: int
    raw: dict[str, Any] | None = None


class OpenClawNativeAdapter:
    def __init__(self, repo_dir: Path, *, agent_id: str = "main", workspace_dir: str = "") -> None:
        self.repo_dir = repo_dir.expanduser()
        self.agent_id = agent_id
        self.workspace_dir = Path(workspace_dir).expanduser() if workspace_dir else None
        self.commands: list[CommandRecord] = []

    def memory_search(self, query: str, *, max_results: int = 5) -> list[str]:
        return self.memory_search_details(query, max_results=max_results).contexts

    def memory_search_details(self, query: str, *, max_results: int = 5) -> MemorySearchDetails:
        started = time.perf_counter()
        result = self._run_full(
            [
                "pnpm",
                "openclaw",
                "memory",
                "search",
                "--query",
                query,
                "--max-results",
                str(max_results),
                "--min-score",
                "0",
                "--json",
                "--agent",
                self.agent_id,
            ]
        )
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        try:
            parsed = _parse_stdout_json_object(result.stdout)
        except Exception:
            contexts = [result.stdout.strip()] if result.stdout.strip() else []
            return MemorySearchDetails(
                contexts=contexts,
                results=[],
                latency_ms=latency_ms,
                raw=None,
            )
        normalized_results = _extract_memory_search_results(parsed)
        contexts = unique_preserve_order(_extract_contexts_from_json(parsed))
        return MemorySearchDetails(
            contexts=contexts,
            results=normalized_results,
            latency_ms=latency_ms,
            raw=parsed,
        )

    def memory_index(self) -> None:
        self._run(["pnpm", "openclaw", "memory", "index", "--force", "--agent", self.agent_id])

    def configure_feishu_group(self, chat_id: str, *, require_mention: bool = True) -> None:
        self.configure_feishu_groups([chat_id], require_mention=require_mention)

    def configure_feishu_groups(
        self, chat_ids: list[str], *, require_mention: bool = True
    ) -> None:
        chat_ids = unique_preserve_order([chat_id for chat_id in chat_ids if chat_id])
        if not chat_ids:
            return
        current = self._read_group_allow_from()
        for chat_id in chat_ids:
            if chat_id not in current:
                current.append(chat_id)
        self._run(["pnpm", "openclaw", "config", "set", "channels.feishu.groupPolicy", "allowlist"])
        self._run(
            [
                "pnpm",
                "openclaw",
                "config",
                "set",
                "channels.feishu.groupAllowFrom",
                dumps_json(current),
                "--strict-json",
            ]
        )
        for chat_id in chat_ids:
            self._run(
                [
                    "pnpm",
                    "openclaw",
                    "config",
                    "set",
                    f"channels.feishu.groups.{chat_id}.requireMention",
                    "true" if require_mention else "false",
                    "--strict-json",
                ]
            )

    def get_default_workspace(self) -> str:
        result = self._run(
            ["pnpm", "openclaw", "config", "get", "agents.defaults.workspace", "--json"]
        )
        parsed = _parse_stdout_json_value(result.stdout)
        if isinstance(parsed, str) and parsed.strip():
            return parsed
        raise BenchmarkError("OpenClaw agents.defaults.workspace is missing or invalid")

    def set_default_workspace(self, workspace_dir: Path) -> None:
        self._run(
            [
                "pnpm",
                "openclaw",
                "config",
                "set",
                "agents.defaults.workspace",
                str(workspace_dir.expanduser()),
            ]
        )

    def get_config_value(self, path: str) -> ConfigValue:
        result = self._run_full(
            ["pnpm", "openclaw", "config", "get", path, "--json"],
            allow_not_found=True,
        )
        if result.record.exit_code != 0:
            return ConfigValue(present=False)
        return ConfigValue(present=True, value=_parse_stdout_json_value(result.stdout))

    def set_config_json(self, path: str, value: Any) -> None:
        self._run(
            [
                "pnpm",
                "openclaw",
                "config",
                "set",
                path,
                dumps_json(value),
                "--strict-json",
            ]
        )

    def unset_config_value(self, path: str) -> None:
        self._run(["pnpm", "openclaw", "config", "unset", path])

    def restart_gateway(self) -> None:
        self._run(["pnpm", "openclaw", "gateway", "restart"])

    def preseed_long_term_memories(self, *, cases: list[BenchmarkCase], run_id: str) -> Path | None:
        del run_id
        records = [
            _format_preseed_message(message)
            for case in cases
            for message in case.seed_messages
            if message.content.strip()
        ]
        if not records:
            return None
        workspace = self.resolve_workspace()
        memory_dir = workspace / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        output_path = memory_dir / "memwing-benchmark-preseed.md"
        output_path.write_text("\n".join(records) + "\n", encoding="utf-8")
        self._run(["pnpm", "openclaw", "memory", "index", "--force", "--agent", self.agent_id])
        return output_path

    def resolve_workspace(self) -> Path:
        if self.workspace_dir:
            return self.workspace_dir
        try:
            result = self._run(
                [
                    "pnpm",
                    "openclaw",
                    "memory",
                    "status",
                    "--deep",
                    "--json",
                    "--agent",
                    self.agent_id,
                ]
            )
            parsed = _parse_stdout_json_value(result.stdout)
            path = _find_workspace_path(parsed)
            if path:
                return Path(path).expanduser()
        except Exception:
            pass
        return Path.home() / ".openclaw" / "workspace"

    def _read_group_allow_from(self) -> list[str]:
        try:
            result = self._run(
                ["pnpm", "openclaw", "config", "get", "channels.feishu.groupAllowFrom", "--json"]
            )
            parsed = _parse_stdout_json_value(result.stdout)
            value = parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
            if isinstance(value, dict) and "value" in value:
                value = value["value"]
            if isinstance(value, list):
                return [str(item) for item in value]
        except Exception:
            return []
        return []

    def _run(self, args: list[str]) -> CommandRecord:
        return self._run_full(args).record

    def _run_full(self, args: list[str], *, allow_not_found: bool = False) -> CommandResult:
        completed = subprocess.run(
            args,
            cwd=self.repo_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        record = CommandRecord(
            command=args,
            cwd=str(self.repo_dir),
            exit_code=completed.returncode,
            stdout=completed.stdout[-4000:],
            stderr=completed.stderr[-4000:],
        )
        self.commands.append(record)
        if completed.returncode != 0:
            combined = f"{completed.stdout}\n{completed.stderr}"
            if allow_not_found and "Config path not found" in combined:
                return CommandResult(
                    record=record, stdout=completed.stdout, stderr=completed.stderr
                )
            raise BenchmarkError(f"OpenClaw command failed: {' '.join(args)}\n{record.stderr}")
        return CommandResult(record=record, stdout=completed.stdout, stderr=completed.stderr)


def _extract_contexts_from_json(value: Any) -> list[str]:
    out: list[str] = []
    for child in walk_values(value):
        if not isinstance(child, dict):
            continue
        for key in ("text", "content", "markdown", "snippet", "body"):
            text = child.get(key)
            if isinstance(text, str) and text.strip():
                out.append(text.strip())
                break
    if out:
        return out
    for child in walk_values(value):
        if isinstance(child, str) and child.strip():
            out.append(child.strip())
    if out:
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return out


def _format_preseed_message(message: SeedMessage) -> str:
    prefix_parts = [part for part in [message.time, message.sender] if part]
    content = message.content.strip()
    if not prefix_parts:
        return content
    return f"{' '.join(prefix_parts)}：{content}"


def _extract_memory_search_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    raw_results = value.get("results")
    if not isinstance(raw_results, list):
        raw_results = value.get("items")
    if not isinstance(raw_results, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_results, start=1):
        if not isinstance(item, dict):
            continue
        snippet = _first_text_value(item)
        normalized.append(
            {
                "rank": index,
                "path": _optional_str(item.get("path")),
                "startLine": _optional_int(item.get("startLine")),
                "endLine": _optional_int(item.get("endLine")),
                "score": _optional_float(item.get("score")),
                "vectorScore": _optional_float(item.get("vectorScore")),
                "textScore": _optional_float(item.get("textScore")),
                "source": _optional_str(item.get("source")),
                "snippet": snippet,
                "raw": item,
            }
        )
    return normalized


def _first_text_value(value: dict[str, Any]) -> str:
    for key in ("snippet", "text", "content", "markdown", "body"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_stdout_json_value(stdout: str) -> Any:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char not in "{[\"":
            continue
        try:
            parsed, _ = decoder.raw_decode(stdout[index:])
            return parsed
        except ValueError:
            continue
    raise ValueError("stdout does not contain JSON")


def _parse_stdout_json_object(stdout: str) -> dict[str, Any]:
    parsed = _parse_stdout_json_value(stdout)
    if not isinstance(parsed, dict):
        raise ValueError("stdout JSON is not an object")
    return parsed


def _find_workspace_path(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"workspace", "workspaceDir", "workspace_dir"} and isinstance(child, str):
                return child
            nested = _find_workspace_path(child)
            if nested:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _find_workspace_path(child)
            if nested:
                return nested
    return None
