from __future__ import annotations

import inspect
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from memwing.api.agent_runtime import RememberEventResult
from memwing.api.platform import PlatformEvent
from memwing.api.types import JsonObject
from memwing.infrastructure.platforms.feishu_connector import (
    FeishuConnector,
    FeishuConnectorError,
)


class PlatformRememberClient(Protocol):
    def remember_event(self, event: PlatformEvent) -> RememberEventResult | Awaitable[RememberEventResult]:
        ...


@dataclass(frozen=True, slots=True)
class PlatformWebhookResponse:
    status_code: int
    body: JsonObject
    platform_event: PlatformEvent | None = None
    remember_result: RememberEventResult | None = None


async def handle_feishu_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
    connector: FeishuConnector,
    remember_client: PlatformRememberClient | None = None,
    received_at: datetime | None = None,
) -> PlatformWebhookResponse:
    received_at = received_at or datetime.now(tz=UTC)
    try:
        connector_result = await connector.handle_webhook(
            headers=headers,
            body=body,
            received_at=received_at,
        )
    except FeishuConnectorError as exc:
        return PlatformWebhookResponse(
            status_code=exc.status_code,
            body={"ok": False, "code": exc.reason_code, "message": str(exc)},
        )

    if connector_result.kind == "challenge":
        return PlatformWebhookResponse(
            status_code=connector_result.status_code,
            body=connector_result.body,
        )

    if connector_result.platform_event is None:
        return PlatformWebhookResponse(
            status_code=500,
            body={"ok": False, "code": "platform_event_missing", "message": "platform event missing"},
        )

    remember_result = None
    if remember_client is not None:
        remembered = remember_client.remember_event(connector_result.platform_event)
        if inspect.isawaitable(remembered):
            remembered = await remembered
        remember_result = remembered

    response_body: JsonObject = {
        "ok": True,
        "raw_payload_hash": connector_result.raw_payload_hash,
        "remembered": remember_result is not None,
    }
    if remember_result is not None:
        response_body["source_event_id"] = remember_result.source_event_id
        response_body["trace_id"] = remember_result.trace_id
        response_body["accepted"] = remember_result.accepted
        if remember_result.duplicate_of is not None:
            response_body["duplicate_of"] = remember_result.duplicate_of

    return PlatformWebhookResponse(
        status_code=connector_result.status_code,
        body=response_body,
        platform_event=connector_result.platform_event,
        remember_result=remember_result,
    )
