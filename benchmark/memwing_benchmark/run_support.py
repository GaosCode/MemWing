from __future__ import annotations

from typing import Any

import typer

from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.schema import utc_now_iso


def confirm_side_effect(description: str, yes: bool) -> None:
    if yes:
        return
    confirmed = typer.confirm(f"将执行外部副作用：{description}。是否继续？")
    if not confirmed:
        raise BenchmarkError(f"用户取消：{description}")


def debug(raw_records: dict[str, Any], message: str, **fields: Any) -> None:
    record = {"at": utc_now_iso(), "message": message, **fields}
    raw_records.setdefault("debug", []).append(record)
    suffix = ""
    if fields:
        suffix = " " + " ".join(f"{key}={value!r}" for key, value in fields.items())
    typer.echo(f"[debug] {message}{suffix}", err=True)


def required_feishu_scopes(*, will_create_chat: bool) -> list[str]:
    scopes = ["im:message.send_as_user"]
    if will_create_chat:
        scopes.append("im:chat:create_by_user")
    return scopes
