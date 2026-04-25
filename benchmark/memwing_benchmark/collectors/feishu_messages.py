from __future__ import annotations

from typing import Any


def normalize_feishu_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": message.get("message_id"),
        "create_time": message.get("create_time"),
        "msg_type": message.get("msg_type"),
        "sender": message.get("sender"),
        "content": message.get("content"),
    }
