from __future__ import annotations

import subprocess
import shutil
import time
from datetime import datetime, timezone
from typing import Any

from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.json_utils import loads_json
from memwing_benchmark.schema import CommandRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FeishuCli:
    def __init__(self, cli_bin: str = "lark-cli") -> None:
        self.cli_bin = cli_bin
        self.commands: list[CommandRecord] = []

    def ensure_ready(self, *, required_scopes: list[str] | None = None) -> None:
        if shutil.which(self.cli_bin) is None:
            raise BenchmarkError(
                "未找到飞书 CLI 包命令。\n"
                "请先安装：npm install -g @larksuite/cli\n"
                f"安装后验证：{self.cli_bin} auth status"
            )
        result = self._run_raw([self.cli_bin, "auth", "status"])
        self._record_completed([self.cli_bin, "auth", "status"], result)
        if result.returncode == 0:
            self._ensure_scopes(result.stdout, required_scopes or [])
            return
        combined = f"{result.stdout}\n{result.stderr}".strip()
        raise BenchmarkError(
            "飞书 CLI 尚未配置或未登录，live benchmark 不能继续。\n"
            "请按包方式完成一次性配置和登录：\n"
            f"1. {self.cli_bin} config init --new\n"
            f"2. {self.cli_bin} auth login --recommend\n"
            f"3. {self.cli_bin} auth status\n\n"
            f"原始错误摘要：{combined[-1000:]}"
        )

    def _ensure_scopes(self, auth_status_stdout: str, required_scopes: list[str]) -> None:
        if not required_scopes:
            return
        try:
            parsed = loads_json(auth_status_stdout)
        except Exception as exc:
            raise BenchmarkError(
                "飞书 CLI 已登录，但无法解析 auth status 输出，不能确认必要 scope。\n"
                f"请手动确认包含：{' '.join(required_scopes)}"
            ) from exc
        scope_text = ""
        if isinstance(parsed, dict):
            scope_text = str(parsed.get("scope", ""))
        granted = set(scope_text.split())
        missing = [scope for scope in required_scopes if scope not in granted]
        if not missing:
            return
        commands = "\n".join(
            f'{index}. {self.cli_bin} auth login --scope "{scope}"'
            for index, scope in enumerate(missing, start=1)
        )
        raise BenchmarkError(
            "飞书 CLI 已登录，但缺少 live benchmark 所需 scope：\n"
            f"{', '.join(missing)}\n\n"
            "请补授权后重试：\n"
            f"{commands}\n"
            f"{len(missing) + 1}. {self.cli_bin} auth status"
        )

    def create_chat(self, *, name: str, bot_app_id: str) -> dict[str, Any]:
        result = self._run(
            [
                self.cli_bin,
                "im",
                "+chat-create",
                "--as",
                "user",
                "--name",
                name,
                "--bots",
                bot_app_id,
                "--format",
                "json",
            ]
        )
        data = _extract_data(result)
        if not data.get("chat_id"):
            raise BenchmarkError("Feishu chat-create did not return chat_id")
        return data

    def send_text(self, *, chat_id: str, text: str, idempotency_key: str) -> dict[str, Any]:
        started_at = _now_iso()
        result = self._run(
            [
                self.cli_bin,
                "im",
                "+messages-send",
                "--as",
                "user",
                "--chat-id",
                chat_id,
                "--text",
                text,
                "--idempotency-key",
                idempotency_key,
            ]
        )
        data = _extract_data(result)
        data.setdefault("sent_at", started_at)
        data["idempotency_key"] = idempotency_key
        return data

    def list_messages(
        self,
        *,
        chat_id: str,
        start: str | None = None,
        end: str | None = None,
        sort: str = "asc",
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        args = [
            self.cli_bin,
            "im",
            "+chat-messages-list",
            "--as",
            "user",
            "--chat-id",
            chat_id,
            "--sort",
            sort,
            "--page-size",
            str(page_size),
            "--format",
            "json",
        ]
        if start:
            args.extend(["--start", start])
        if end:
            args.extend(["--end", end])
        result = self._run(args)
        data = _extract_data(result)
        messages = data.get("messages", data.get("items", []))
        if not isinstance(messages, list):
            raise BenchmarkError("Feishu chat-messages-list returned invalid messages")
        return [msg for msg in messages if isinstance(msg, dict)]

    def wait_for_bot_reply(
        self,
        *,
        chat_id: str,
        since: str,
        bot_open_id: str,
        timeout_seconds: float,
        poll_seconds: float = 3.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            messages = self.list_messages(chat_id=chat_id, start=since, sort="asc")
            for message in messages:
                if _is_bot_message(message, bot_open_id):
                    return message
            time.sleep(poll_seconds)
        raise BenchmarkError(f"Timed out waiting for bot reply after {timeout_seconds:.0f}s")

    def _run(self, args: list[str]) -> dict[str, Any]:
        completed = self._run_raw(args)
        self._record_completed(args, completed)
        if completed.returncode != 0:
            raise BenchmarkError(_format_cli_failure(args, completed.stdout, completed.stderr))
        try:
            parsed = loads_json(completed.stdout)
        except Exception as exc:
            raise BenchmarkError(
                f"Feishu CLI returned non-JSON output: {completed.stdout[:500]}"
            ) from exc
        if not isinstance(parsed, dict):
            raise BenchmarkError("Feishu CLI returned non-object JSON")
        return parsed

    def _run_raw(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _record_completed(
        self, args: list[str], completed: subprocess.CompletedProcess[str]
    ) -> None:
        self.commands.append(
            CommandRecord(
                command=args,
                cwd=None,
                exit_code=completed.returncode,
                stdout=completed.stdout[-4000:],
                stderr=completed.stderr[-4000:],
            )
        )


def _format_cli_failure(args: list[str], stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}".strip()
    hint = ""
    if "not configured" in combined or "config init" in combined:
        cli_bin = args[0] if args else "lark-cli"
        hint = (
            "\n\n飞书 CLI 需要先按包方式配置和登录：\n"
            f"1. {cli_bin} config init --new\n"
            f"2. {cli_bin} auth login --recommend\n"
            f"3. {cli_bin} auth status"
        )
    return f"Feishu CLI command failed: {' '.join(args)}\n{combined[-1000:]}{hint}"


def _extract_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data", result)
    if not isinstance(data, dict):
        raise BenchmarkError("CLI JSON data is not an object")
    return data


def _is_bot_message(message: dict[str, Any], bot_open_id: str) -> bool:
    sender = message.get("sender")
    if isinstance(sender, dict):
        possible_ids = {
            str(sender.get("open_id", "")),
            str(sender.get("id", "")),
            str(sender.get("sender_id", "")),
            str(sender.get("user_id", "")),
        }
        if bot_open_id in possible_ids:
            return True
        sender_type = str(sender.get("type", sender.get("sender_type", ""))).lower()
        if sender_type in {"app", "bot"} and not bot_open_id:
            return True
    return False
