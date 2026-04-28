import asyncio

import pytest

from memwing.infrastructure.platforms.feishu_connector import (
    FeishuConnector,
    FeishuConnectorError,
)
from tests.unit.feishu_connector_test_support import (
    RECEIVED_AT,
    SECRET,
    FakeAuditSink,
    FakeDecryptor,
    signed_headers,
)


def test_plain_challenge_bypasses_formal_signature_headers() -> None:
    audit = FakeAuditSink()
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        verification_token="token_001",
        audit_sink=audit,
    )

    result = asyncio.run(
        connector.handle_webhook(
            headers={},
            body=b'{"challenge":"challenge_001","token":"token_001","type":"url_verification"}',
            received_at=RECEIVED_AT,
        )
    )

    assert result.status_code == 200
    assert result.body == {"challenge": "challenge_001"}
    assert audit.records == []


def test_signed_encrypted_challenge_uses_decryptor_after_formal_signature() -> None:
    decryptor = FakeDecryptor(
        {"challenge": "challenge_002", "token": "token_001", "type": "url_verification"}
    )
    body = b'{"encrypt":"cipher_challenge"}'
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        verification_token="token_001",
        decryptor=decryptor,
    )

    result = asyncio.run(
        connector.handle_webhook(
            headers=signed_headers(body),
            body=body,
            received_at=RECEIVED_AT,
        )
    )

    assert result.body == {"challenge": "challenge_002"}
    assert decryptor.calls == ["decrypt:cipher_challenge"]


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


def test_encrypted_request_with_partial_formal_headers_fails_before_decrypting() -> None:
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

    with pytest.raises(FeishuConnectorError, match="nonce_missing"):
        asyncio.run(
            connector.handle_webhook(
                headers={"X-Lark-Request-Timestamp": str(int(RECEIVED_AT.timestamp()))},
                body=b'{"encrypt":"cipher_challenge"}',
                received_at=RECEIVED_AT,
            )
        )

    assert decryptor.calls == []
    assert [record.reason_code for record in audit.records] == ["nonce_missing"]
