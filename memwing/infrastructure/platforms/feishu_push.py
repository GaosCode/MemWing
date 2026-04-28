from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import Protocol

from memwing.api.platform import PlatformRef, PlatformSendResult, PushCandidate


class FeishuPushSender(Protocol):
    def send_text(
        self,
        platform_ref: PlatformRef,
        content: str,
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

        provider_message_id = self._push_sender.send_text(
            candidate.platform_ref,
            candidate.content,
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
