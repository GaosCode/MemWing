import asyncio
import json
from datetime import UTC, datetime

from memwing.api.platform_webhooks import handle_feishu_webhook
from memwing.infrastructure.platforms.feishu_connector import FeishuConnector


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)


def test_feishu_webhook_api_returns_encrypted_challenge_without_formal_signature() -> None:
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        decryptor=StaticDecryptor({"challenge": "challenge_001"}),
    )

    response = asyncio.run(
        handle_feishu_webhook(
            headers={},
            body=b'{"encrypt":"cipher_challenge"}',
            connector=connector,
            received_at=RECEIVED_AT,
        )
    )

    assert response.status_code == 200
    assert response.body == {"challenge": "challenge_001"}


def test_feishu_webhook_api_returns_clear_error_for_invalid_schema() -> None:
    connector = FeishuConnector(project_memory_space_id="project_001", signing_secret="secret_001")
    body = b'{"event":{"message":{"content":"{\\"text\\":\\"missing chat\\"}"}}}'

    response = asyncio.run(
        handle_feishu_webhook(
            headers=_signed_headers(body),
            body=body,
            connector=connector,
            received_at=RECEIVED_AT,
        )
    )

    assert response.status_code == 400
    assert response.body["ok"] is False
    assert response.body["code"] == "schema_invalid"


def _signed_headers(body: bytes) -> dict[str, str]:
    from memwing.infrastructure.platforms.feishu_connector import compute_feishu_signature

    timestamp = str(int(RECEIVED_AT.timestamp()))
    nonce = "nonce_001"
    return {
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": compute_feishu_signature(
            signing_secret="secret_001",
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        ),
    }


class StaticDecryptor:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def decrypt(self, encrypted_text: str) -> str:
        return json.dumps(self._payload)
