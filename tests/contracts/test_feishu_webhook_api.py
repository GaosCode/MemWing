import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime

from memwing.api.platform_webhooks import handle_feishu_webhook
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
