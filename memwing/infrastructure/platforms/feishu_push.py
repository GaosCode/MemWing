from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable
from typing import Protocol

from memwing.api.platform import PlatformRef, PlatformSendResult, PushCandidate
from memwing.core.types import JsonObject


class FeishuPushSender(Protocol):
    def send_interactive_message(
        self,
        platform_ref: PlatformRef,
        payload: JsonObject,
        trace_id: str,
    ) -> str | Awaitable[str]:
        ...


class FeishuPushDispatcher:
    def __init__(self, push_sender: FeishuPushSender | None = None) -> None:
        self._push_sender = push_sender

    async def send_candidate(self, candidate: PushCandidate) -> PlatformSendResult:
        if self._push_sender is None:
            return PlatformSendResult(
                candidate_id=candidate.id,
                delivered=False,
                trace_id=candidate.trace_id,
            )

        provider_message_id = self._push_sender.send_interactive_message(
            candidate.platform_ref,
            _interactive_message_payload(candidate),
            candidate.trace_id,
        )
        if inspect.isawaitable(provider_message_id):
            provider_message_id = await provider_message_id
        return PlatformSendResult(
            candidate_id=candidate.id,
            delivered=True,
            trace_id=candidate.trace_id,
            provider_message_id=provider_message_id,
        )


def _interactive_message_payload(candidate: PushCandidate) -> JsonObject:
    return {
        "receive_id": candidate.platform_ref.channel_id,
        "msg_type": "interactive",
        "content": json.dumps(_interactive_card(candidate), ensure_ascii=False, separators=(",", ":")),
    }


def _interactive_card(candidate: PushCandidate) -> JsonObject:
    title = candidate.title or "MemWing push candidate"
    kind = candidate.kind or "push_candidate"
    return {
        "config": {
            "wide_screen_mode": True,
            "update_multi": True,
        },
        "header": {
            "template": _card_template(kind),
            "title": {
                "tag": "plain_text",
                "content": _clip(title, 80),
            },
        },
        "elements": (
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": _clip(candidate.content, 1600),
                },
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": (
                    {
                        "tag": "plain_text",
                        "content": f"MemWing | {kind} | trace {candidate.trace_id}",
                    },
                ),
            },
        ),
    }


def _card_template(kind: str) -> str:
    if kind == "forgetting_review":
        return "orange"
    if kind == "decision_card":
        return "blue"
    return "turquoise"


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."
