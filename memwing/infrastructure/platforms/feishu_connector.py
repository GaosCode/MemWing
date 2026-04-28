from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from memwing.api.platform import (
    PlatformEvent,
    PlatformRawEvent,
    PlatformRawRequest,
    PlatformSendResult,
    PushCandidate,
)
from memwing.infrastructure.platforms.feishu_push import (
    FeishuPushDispatcher,
    FeishuPushSender,
)
from memwing.infrastructure.platforms.feishu_security import (
    FeishuAuditRecord,
    FeishuAuditSink,
    FeishuConnectorError,
    FeishuReplayProtector,
    compute_feishu_signature,
)
from memwing.infrastructure.platforms.feishu_webhook import (
    FeishuDecryptor,
    FeishuWebhookHandler,
    FeishuWebhookKind,
    FeishuWebhookResult,
)


__all__ = [
    "FeishuAuditRecord",
    "FeishuConnector",
    "FeishuConnectorError",
    "FeishuDecryptor",
    "FeishuPushSender",
    "FeishuWebhookKind",
    "FeishuWebhookResult",
    "compute_feishu_signature",
]


class FeishuConnector:
    def __init__(
        self,
        *,
        project_memory_space_id: str,
        signing_secret: str | None = None,
        verification_token: str | None = None,
        max_body_bytes: int = 256 * 1024,
        max_timestamp_skew_seconds: int = 300,
        decryptor: FeishuDecryptor | None = None,
        replay_protector: FeishuReplayProtector | None = None,
        audit_sink: FeishuAuditSink | None = None,
        push_sender: FeishuPushSender | None = None,
    ) -> None:
        self._webhook_handler = FeishuWebhookHandler(
            project_memory_space_id=project_memory_space_id,
            signing_secret=signing_secret,
            verification_token=verification_token,
            max_body_bytes=max_body_bytes,
            max_timestamp_skew_seconds=max_timestamp_skew_seconds,
            decryptor=decryptor,
            replay_protector=replay_protector,
            audit_sink=audit_sink,
        )
        self._push_dispatcher = FeishuPushDispatcher(push_sender)

    async def handle_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        received_at: datetime | None = None,
    ) -> FeishuWebhookResult:
        return await self._webhook_handler.handle_webhook(
            headers=headers,
            body=body,
            received_at=received_at,
        )

    async def verify_request(self, raw_request: PlatformRawRequest) -> bool:
        return await self._webhook_handler.verify_request(raw_request)

    async def normalize_event(self, raw_event: PlatformRawEvent) -> PlatformEvent:
        return await self._webhook_handler.normalize_event(raw_event)

    async def send_candidate(self, candidate: PushCandidate) -> PlatformSendResult:
        return await self._push_dispatcher.send_candidate(candidate)
