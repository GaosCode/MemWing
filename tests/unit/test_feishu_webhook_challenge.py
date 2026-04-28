import asyncio
import json
from datetime import UTC, datetime

from memwing.infrastructure.platforms.feishu_connector import (
    FeishuAuditRecord,
    FeishuConnector,
)


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
SECRET = "secret_001"


def test_encrypted_challenge_bypasses_formal_signature_headers() -> None:
    audit = FakeAuditSink()
    decryptor = FakeDecryptor(
        {"challenge": "challenge_001", "token": "token_001", "type": "url_verification"}
    )
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        verification_token="token_001",
        decryptor=decryptor,
        audit_sink=audit,
    )

    result = asyncio.run(
        connector.handle_webhook(
            headers={},
            body=b'{"encrypt":"cipher_challenge"}',
            received_at=RECEIVED_AT,
        )
    )

    assert result.status_code == 200
    assert result.body == {"challenge": "challenge_001"}
    assert decryptor.calls == ["decrypt:cipher_challenge"]
    assert audit.records == []


class FakeAuditSink:
    def __init__(self) -> None:
        self.records: list[FeishuAuditRecord] = []

    def record(self, record: FeishuAuditRecord) -> None:
        self.records.append(record)


class FakeDecryptor:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.calls: list[str] = []

    def decrypt(self, encrypted_text: str) -> str:
        self.calls.append(f"decrypt:{encrypted_text}")
        return json.dumps(self._payload)
