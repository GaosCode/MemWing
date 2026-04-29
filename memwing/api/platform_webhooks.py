from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from memwing.api.agent_runtime import RememberEventResult
from memwing.api.platform import PlatformRawEvent
from memwing.api.types import JsonObject
from memwing.application.platform_ingress_service import PlatformIngressService
from memwing.application.scope_resolver import ScopeResolutionError
from memwing.ports.platform_webhook import (
    PlatformWebhookError,
    PlatformWebhookHandlerPort,
)


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
    ingress_service: PlatformIngressService | None = None,
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
        if ingress_service is not None and exc.raw_payload_hash is not None:
            await ingress_service.record_transport_failure(
                platform="feishu",
                reason_code=exc.reason_code,
                raw_payload_hash=exc.raw_payload_hash,
                status_code=exc.status_code,
                received_at=received_at,
            )
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

    if ingress_service is None:
        return PlatformWebhookResponse(
            status_code=500,
            body={
                "ok": False,
                "code": "platform_ingress_service_missing",
                "message": "platform ingress service is not configured",
            },
            raw_event=connector_result.raw_event,
        )

    try:
        remember_result = await ingress_service.ingest(connector_result.raw_event)
    except ScopeResolutionError as exc:
        return PlatformWebhookResponse(
            status_code=403,
            body={
                "ok": False,
                "code": "scope_resolution_failed",
                "message": str(exc),
                "raw_payload_hash": connector_result.raw_payload_hash,
            },
            raw_event=connector_result.raw_event,
        )

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
