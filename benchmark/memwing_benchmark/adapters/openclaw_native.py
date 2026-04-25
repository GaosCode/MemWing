from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.json_utils import dumps_json, loads_json, walk_values
from memwing_benchmark.metrics.retrieval import extract_evidence_ids, unique_preserve_order
from memwing_benchmark.schema import BenchmarkCase, CommandRecord


class OpenClawNativeAdapter:
    def __init__(self, repo_dir: Path, *, agent_id: str = "main", workspace_dir: str = "") -> None:
        self.repo_dir = repo_dir.expanduser()
        self.agent_id = agent_id
        self.workspace_dir = Path(workspace_dir).expanduser() if workspace_dir else None
        self.commands: list[CommandRecord] = []

    def memory_search(self, query: str, *, max_results: int = 5) -> list[str]:
        result = self._run(
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
        try:
            parsed = loads_json(result.stdout)
        except Exception:
            return extract_evidence_ids(result.stdout)
        return unique_preserve_order(_extract_evidence_from_json(parsed))

    def configure_feishu_group(self, chat_id: str) -> None:
        current = self._read_group_allow_from()
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
        self._run(
            [
                "pnpm",
                "openclaw",
                "config",
                "set",
                f"channels.feishu.groups.{chat_id}.requireMention",
                "true",
                "--strict-json",
            ]
        )

    def restart_gateway(self) -> None:
        self._run(["pnpm", "openclaw", "gateway", "restart"])

    def preseed_long_term_memories(self, *, cases: list[BenchmarkCase], run_id: str) -> Path | None:
        memories = [memory for case in cases for memory in case.preseed_memories]
        if not memories:
            return None
        workspace = self.resolve_workspace()
        memory_dir = workspace / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        output_path = memory_dir / f"memwing-benchmark-{run_id}.md"
        blocks: list[str] = []
        for memory in memories:
            title = memory.title or memory.memory_id
            evidence = ", ".join(memory.gold_evidence_ids or [memory.memory_id])
            blocks.append(
                "\n".join(
                    [
                        f"## [MEM:{memory.memory_id}] {title}",
                        "",
                        f"- 时间：{memory.memory_time or 'unknown'}",
                        "- 来源：MemWing benchmark v1 preseed",
                        f"- 内容：{memory.content}",
                        f"- 证据编号：{evidence}",
                    ]
                )
            )
        output_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
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
            parsed = loads_json(result.stdout)
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
            parsed = loads_json(result.stdout)
            value = parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
            if isinstance(value, dict) and "value" in value:
                value = value["value"]
            if isinstance(value, list):
                return [str(item) for item in value]
        except Exception:
            return []
        return []

    def _run(self, args: list[str]) -> CommandRecord:
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
            raise BenchmarkError(f"OpenClaw command failed: {' '.join(args)}\n{record.stderr}")
        return record


def _extract_evidence_from_json(value: Any) -> list[str]:
    out: list[str] = []
    for child in walk_values(value):
        if isinstance(child, str):
            out.extend(extract_evidence_ids(child))
    return out


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
