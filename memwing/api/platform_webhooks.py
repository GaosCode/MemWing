from __future__ import annotations

import inspect
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from memwing.api.agent_runtime import RememberEventResult
from memwing.api.platform import PlatformEvent, PlatformRawEvent
from memwing.api.types import JsonObject
from memwing.application.remember_event_command import (
    RememberEventCommand,
    platform_event_to_remember_command,
)
from memwing.ports.platform_webhook import (
    PlatformWebhookError,
    PlatformWebhookHandlerPort,
)


class PlatformRememberClient(Protocol):
    def remember_event(
        self,
        command: RememberEventCommand,
    ) -> RememberEventResult | Awaitable[RememberEventResult]:
        ...


class PlatformEventNormalizer(Protocol):
    def normalize_event(self, raw_event: PlatformRawEvent) -> PlatformEvent | Awaitable[PlatformEvent]:
        ...


@dataclass(frozen=True, slots=True)
class PlatformWebhookResponse:
    status_code: int
    body: JsonObject
    raw_event: PlatformRawEvent | None = None
    remember_result: RememberEventResult | None = None


async def handle_feishu_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
    connector: PlatformWebhookHandlerPort,
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
    except PlatformWebhookError as exc:
        return PlatformWebhookResponse(
            status_code=exc.status_code,
            body={"ok": False, "code": exc.reason_code, "message": str(exc)},
        )

    if connector_result.kind == "challenge":
        return PlatformWebhookResponse(
            status_code=connector_result.status_code,
            body=connector_result.body,
        )

    if connector_result.kind == "rejected":
        return PlatformWebhookResponse(
            status_code=connector_result.status_code,
            body=connector_result.body,
        )

    if connector_result.raw_event is None:
        return PlatformWebhookResponse(
            status_code=500,
            body={"ok": False, "code": "platform_raw_event_missing", "message": "platform raw event missing"},
        )

    remember_result = None
    if remember_client is not None:
        platform_event = await _normalize_platform_event(connector, connector_result.raw_event)
        remembered = remember_client.remember_event(
            platform_event_to_remember_command(platform_event)
        )
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
        raw_event=connector_result.raw_event,
        remember_result=remember_result,
    )


async def _normalize_platform_event(
    connector: PlatformWebhookHandlerPort,
    raw_event: PlatformRawEvent,
) -> PlatformEvent:
    normalizer = getattr(connector, "normalize_event", None)
    if normalizer is None:
        raise TypeError("connector must normalize PlatformRawEvent before remember_event")
    normalized = normalizer(raw_event)
    if inspect.isawaitable(normalized):
        normalized = await normalized
    return normalized
