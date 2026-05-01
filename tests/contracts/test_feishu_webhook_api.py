import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime

from memwing.api.platform import PlatformRawEvent, PlatformRawRequest, PlatformRef
from memwing.api.platform_webhooks import handle_feishu_webhook
from memwing.application.scope_resolver import ScopeResolutionError
from memwing.ports.platform_webhook import PlatformWebhookError, PlatformWebhookResult


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)


def test_feishu_webhook_api_returns_challenge_response() -> None:
    connector = FakeWebhookConnector(
        PlatformWebhookResult(
            kind="challenge",
            status_code=200,
            body={"challenge": "challenge_001"},
            raw_payload_hash="hash_001",
        )
    )

    response = asyncio.run(
        handle_feishu_webhook(
            headers={},
            body=b'{"challenge":"challenge_001"}',
            connector=connector,
            received_at=RECEIVED_AT,
        )
    )

    assert response.status_code == 200
    assert response.body == {"challenge": "challenge_001"}


def test_feishu_webhook_api_returns_clear_error_for_invalid_schema() -> None:
    connector = FailingWebhookConnector(
        PlatformWebhookError("schema_invalid", "schema_invalid", 400)
    )
    body = b'{"event":{"message":{"content":"{\\"text\\":\\"missing chat\\"}"}}}'

    response = asyncio.run(
        handle_feishu_webhook(
            headers={},
            body=body,
            connector=connector,
            received_at=RECEIVED_AT,
        )
    )

    assert response.status_code == 400
    assert response.body["ok"] is False
    assert response.body["code"] == "schema_invalid"


def test_feishu_webhook_api_requires_ingress_service_for_accepted_events() -> None:
    connector = FakeWebhookConnector(
        PlatformWebhookResult(
            kind="accepted",
            status_code=202,
            body={"ok": True},
            raw_payload_hash="hash_001",
            raw_event=_raw_event(),
        )
    )

    response = asyncio.run(
        handle_feishu_webhook(
            headers={},
            body=b'{"event":{"message":{"chat_id":"chat_001","content":"hello"}}}',
            connector=connector,
            received_at=RECEIVED_AT,
        )
    )

    assert response.status_code == 500
    assert response.body == {
        "ok": False,
        "code": "platform_ingress_service_missing",
        "message": "platform ingress service is not configured",
    }
    assert "remembered" not in response.body


def test_feishu_webhook_api_renders_scope_errors_through_safe_error_mapping() -> None:
    connector = FakeWebhookConnector(
        PlatformWebhookResult(
            kind="accepted",
            status_code=202,
            body={"ok": True},
            raw_payload_hash="hash_001",
            raw_event=_raw_event(),
        )
    )

    response = asyncio.run(
        handle_feishu_webhook(
            headers={},
            body=b'{"event":{"message":{"chat_id":"chat_001","content":"hello"}}}',
            connector=connector,
            ingress_service=FailingIngressService(),
            received_at=RECEIVED_AT,
        )
    )

    assert response.status_code == 403
    assert response.body["ok"] is False
    assert response.body["code"] == "scope_resolution_failed"
    assert response.body["message"] == "Memory scope is not available."
    assert response.body["raw_payload_hash"] == "hash_001"


class FakeWebhookConnector:
    def __init__(self, result: PlatformWebhookResult) -> None:
        self._result = result
        self.calls: list[tuple[dict[str, str], bytes, datetime | None]] = []

    async def handle_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        received_at: datetime | None = None,
    ) -> PlatformWebhookResult:
        self.calls.append((dict(headers), body, received_at))
        return self._result


class FailingWebhookConnector:
    def __init__(self, error: PlatformWebhookError) -> None:
        self._error = error

    async def handle_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        received_at: datetime | None = None,
    ) -> PlatformWebhookResult:
        raise self._error


class FailingIngressService:
    async def ingest(self, raw_event: PlatformRawEvent):
        raise ScopeResolutionError("raw object existence must not leak")


def _raw_event() -> PlatformRawEvent:
    raw_request = PlatformRawRequest(
        platform="feishu",
        headers={},
        body=b'{"event":{"message":{"chat_id":"chat_001","content":"hello"}}}',
        received_at=RECEIVED_AT,
        raw_payload_hash="hash_001",
    )
    return PlatformRawEvent(
        platform_ref=PlatformRef(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id=None,
            message_id="message_001",
        ),
        raw_request=raw_request,
        event_payload={"event": {"message": {"chat_id": "chat_001", "content": "hello"}}},
        is_challenge=False,
    )
