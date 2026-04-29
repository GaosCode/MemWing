import asyncio
import json
from datetime import timedelta

import pytest

from memwing.infrastructure.platforms import feishu_webhook as feishu_webhook_module
from memwing.infrastructure.platforms.feishu_connector import (
    FeishuConnector,
    FeishuConnectorError,
)
from tests.unit.feishu_connector_test_support import (
    RECEIVED_AT,
    SECRET,
    FailingDecryptor,
    FakeAuditSink,
    FakeDecryptor,
    RecordingReplayProtector,
    build_message_payload,
    signed_headers,
)


def test_unsigned_challenge_with_event_shape_fails_formal_security_check() -> None:
    audit = FakeAuditSink()
    body = b'{"challenge":"challenge_001","event":{"message":{"chat_id":"oc_group_001"}}}'
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="timestamp_missing"):
        asyncio.run(
            connector.handle_webhook(
                headers={},
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert [record.reason_code for record in audit.records] == ["timestamp_missing"]
    assert "challenge_001" not in str(audit.records[0].details)
    assert "oc_group_001" not in str(audit.records[0].details)


def test_unsigned_encrypted_event_fails_formal_security_after_challenge_probe() -> None:
    audit = FakeAuditSink()
    decryptor = FakeDecryptor(build_message_payload())
    body = b'{"encrypt":"cipher_event"}'
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        decryptor=decryptor,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="timestamp_missing"):
        asyncio.run(
            connector.handle_webhook(
                headers={},
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert decryptor.calls == ["decrypt:cipher_event"]
    assert [record.reason_code for record in audit.records] == ["timestamp_missing"]


def test_formal_event_verifies_signature_then_replay_then_decrypts() -> None:
    calls: list[str] = []
    payload = build_message_payload()
    encrypted_body = json.dumps({"encrypt": "cipher_event"}).encode()
    decryptor = FakeDecryptor(payload, calls=calls)
    replay = RecordingReplayProtector(calls)
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        decryptor=decryptor,
        replay_protector=replay,
    )

    result = asyncio.run(
        connector.handle_webhook(
            headers=signed_headers(encrypted_body),
            body=encrypted_body,
            received_at=RECEIVED_AT,
        )
    )

    assert result.raw_event is not None
    platform_event = asyncio.run(connector.normalize_event(result.raw_event))
    assert platform_event.content == "Remember encrypted events."
    assert calls == ["replay", "decrypt:cipher_event"]


def test_bad_signature_is_audited_and_not_decrypted() -> None:
    audit = FakeAuditSink()
    decryptor = FakeDecryptor(build_message_payload())
    body = json.dumps({"encrypt": "cipher_event"}).encode()
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        decryptor=decryptor,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="signature_mismatch"):
        asyncio.run(
            connector.handle_webhook(
                headers={
                    "X-Lark-Request-Timestamp": str(int(RECEIVED_AT.timestamp())),
                    "X-Lark-Request-Nonce": "nonce_001",
                    "X-Lark-Signature": "bad",
                },
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert [record.reason_code for record in audit.records] == ["signature_mismatch"]
    assert decryptor.calls == []
    assert "cipher_event" not in str(audit.records[0].details)


@pytest.mark.parametrize("body", (b'{"encrypt":"cipher_event"}', b"{not-json"))
def test_full_formal_headers_bad_signature_does_not_parse_json_before_signature(
    body: bytes,
) -> None:
    audit = FakeAuditSink()
    parse_calls: list[bytes] = []
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )

    def fail_if_parsed(candidate: bytes) -> dict[str, object]:
        parse_calls.append(candidate)
        return {}

    connector._decode_body = fail_if_parsed

    with pytest.raises(FeishuConnectorError, match="signature_mismatch"):
        asyncio.run(
            connector.handle_webhook(
                headers={
                    "X-Lark-Request-Timestamp": str(int(RECEIVED_AT.timestamp())),
                    "X-Lark-Request-Nonce": "nonce_001",
                    "X-Lark-Signature": "bad",
                },
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert parse_calls == []
    assert [record.reason_code for record in audit.records] == ["signature_mismatch"]


def test_oversized_body_checks_size_before_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = FakeAuditSink()
    order: list[str] = []

    class OversizedBody:
        def __len__(self) -> int:
            order.append("len")
            return 2

    def fake_raw_payload_hash(body: object) -> str:
        order.append("hash")
        return "oversized_hash"

    monkeypatch.setattr(feishu_webhook_module, "raw_payload_hash", fake_raw_payload_hash)
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        max_body_bytes=1,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="body_too_large"):
        asyncio.run(
            connector.handle_webhook(headers={}, body=OversizedBody(), received_at=RECEIVED_AT)
        )

    assert order == ["len", "hash"]
    assert audit.records[0].reason_code == "body_too_large"
    assert audit.records[0].raw_payload_hash == "oversized_hash"


def test_empty_body_with_bad_signature_audits_signature_before_dto_or_schema() -> None:
    audit = FakeAuditSink()
    body = b""
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="signature_mismatch"):
        asyncio.run(
            connector.handle_webhook(
                headers={
                    "X-Lark-Request-Timestamp": str(int(RECEIVED_AT.timestamp())),
                    "X-Lark-Request-Nonce": "nonce_001",
                    "X-Lark-Signature": "bad",
                },
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert [record.reason_code for record in audit.records] == ["signature_mismatch"]


def test_empty_body_with_valid_signature_schemas_after_replay() -> None:
    audit = FakeAuditSink()
    calls: list[str] = []
    replay = RecordingReplayProtector(calls)
    body = b""
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        replay_protector=replay,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="schema_invalid"):
        asyncio.run(
            connector.handle_webhook(
                headers=signed_headers(body),
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert calls == ["replay"]
    assert [record.reason_code for record in audit.records] == ["schema_invalid"]


@pytest.mark.parametrize(
    ("header_name", "reason_code"),
    (
        ("X-Lark-Request-Timestamp", "timestamp_missing"),
        ("X-Lark-Request-Nonce", "nonce_missing"),
        ("X-Lark-Signature", "signature_missing"),
    ),
)
def test_empty_formal_header_values_are_audited_by_required_header(
    header_name: str,
    reason_code: str,
) -> None:
    audit = FakeAuditSink()
    body = json.dumps(build_message_payload()).encode()
    headers = signed_headers(body)
    headers[header_name] = ""
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match=reason_code):
        asyncio.run(
            connector.handle_webhook(headers=headers, body=body, received_at=RECEIVED_AT)
        )

    assert [record.reason_code for record in audit.records] == [reason_code]


def test_oversized_timestamp_is_audited_as_timestamp_invalid() -> None:
    audit = FakeAuditSink()
    body = json.dumps(build_message_payload()).encode()
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="timestamp_invalid"):
        asyncio.run(
            connector.handle_webhook(
                headers=signed_headers(body, timestamp="9" * 400),
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert [record.reason_code for record in audit.records] == ["timestamp_invalid"]


def test_signed_invalid_json_with_bad_signature_audits_signature_before_schema() -> None:
    audit = FakeAuditSink()
    body = b"{not-json"
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="signature_mismatch"):
        asyncio.run(
            connector.handle_webhook(
                headers={
                    "X-Lark-Request-Timestamp": str(int(RECEIVED_AT.timestamp())),
                    "X-Lark-Request-Nonce": "nonce_001",
                    "X-Lark-Signature": "bad",
                },
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert [record.reason_code for record in audit.records] == ["signature_mismatch"]


def test_signed_invalid_json_with_valid_signature_schemas_after_replay() -> None:
    audit = FakeAuditSink()
    calls: list[str] = []
    replay = RecordingReplayProtector(calls)
    body = b"{not-json"
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        replay_protector=replay,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="schema_invalid"):
        asyncio.run(
            connector.handle_webhook(
                headers=signed_headers(body),
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert calls == ["replay"]
    assert [record.reason_code for record in audit.records] == ["schema_invalid"]


def test_replay_is_audited_by_timestamp_nonce_and_raw_hash() -> None:
    audit = FakeAuditSink()
    body = json.dumps(build_message_payload()).encode()
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )
    headers = signed_headers(body)

    first = asyncio.run(
        connector.handle_webhook(headers=headers, body=body, received_at=RECEIVED_AT)
    )
    assert first.status_code == 202

    with pytest.raises(FeishuConnectorError, match="nonce_replayed"):
        asyncio.run(
            connector.handle_webhook(headers=headers, body=body, received_at=RECEIVED_AT)
        )

    assert [record.reason_code for record in audit.records] == ["nonce_replayed"]


def test_timestamp_expiry_and_body_limit_failures_are_audited() -> None:
    audit = FakeAuditSink()
    body = json.dumps(build_message_payload()).encode()
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        max_body_bytes=len(body) + 1,
        audit_sink=audit,
    )
    expired_at = RECEIVED_AT - timedelta(minutes=10)

    with pytest.raises(FeishuConnectorError, match="timestamp_expired"):
        asyncio.run(
            connector.handle_webhook(
                headers=signed_headers(body, timestamp=str(int(expired_at.timestamp()))),
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    too_small = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        max_body_bytes=1,
        audit_sink=audit,
    )
    with pytest.raises(FeishuConnectorError, match="body_too_large"):
        asyncio.run(
            too_small.handle_webhook(headers=signed_headers(body), body=body, received_at=RECEIVED_AT)
        )

    assert [record.reason_code for record in audit.records] == [
        "timestamp_expired",
        "body_too_large",
    ]


def test_decrypt_failure_and_schema_invalid_are_audited() -> None:
    audit = FakeAuditSink()
    encrypted_body = json.dumps({"encrypt": "broken"}).encode()
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        decryptor=FailingDecryptor(),
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="decrypt_failed"):
        asyncio.run(
            connector.handle_webhook(
                headers=signed_headers(encrypted_body),
                body=encrypted_body,
                received_at=RECEIVED_AT,
            )
        )

    body = json.dumps({"event": {"message": {"content": '{"text":"missing chat"}'}}}).encode()
    schema_connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )
    with pytest.raises(FeishuConnectorError, match="schema_invalid"):
        asyncio.run(
            schema_connector.handle_webhook(
                headers=signed_headers(body),
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert [record.reason_code for record in audit.records] == [
        "decrypt_failed",
        "schema_invalid",
    ]


def test_payload_create_time_overflow_is_audited_as_schema_invalid() -> None:
    audit = FakeAuditSink()
    calls: list[str] = []
    replay = RecordingReplayProtector(calls)
    payload = build_message_payload()
    event = payload["event"]
    assert isinstance(event, dict)
    message = event["message"]
    assert isinstance(message, dict)
    message["create_time"] = "9" * 400
    body = json.dumps(payload).encode()
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        replay_protector=replay,
        audit_sink=audit,
    )

    with pytest.raises(FeishuConnectorError, match="schema_invalid"):
        asyncio.run(
            connector.handle_webhook(
                headers=signed_headers(body),
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert calls == ["replay"]
    assert [record.reason_code for record in audit.records] == ["schema_invalid"]
