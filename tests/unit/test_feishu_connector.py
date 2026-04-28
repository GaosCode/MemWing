import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from memwing.api.platform import PlatformRef, PushCandidate
from memwing.infrastructure.platforms.feishu_connector import (
    FeishuAuditRecord,
    FeishuConnector,
    FeishuConnectorError,
    compute_feishu_signature,
)


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
SECRET = "secret_001"


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


def test_encrypted_challenge_uses_decryptor_without_formal_signature_headers() -> None:
    decryptor = FakeDecryptor({"challenge": "challenge_002", "token": "token_001"})
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        verification_token="token_001",
        decryptor=decryptor,
    )

    result = asyncio.run(
        connector.handle_webhook(
            headers={},
            body=b'{"encrypt":"cipher_challenge"}',
            received_at=RECEIVED_AT,
        )
    )

    assert result.body == {"challenge": "challenge_002"}
    assert decryptor.calls == ["decrypt:cipher_challenge"]


def test_formal_event_verifies_signature_then_replay_then_decrypts() -> None:
    calls: list[str] = []
    payload = _message_payload()
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
            headers=_signed_headers(encrypted_body),
            body=encrypted_body,
            received_at=RECEIVED_AT,
        )
    )

    assert result.platform_event is not None
    assert result.platform_event.content == "Remember encrypted events."
    assert calls == ["replay", "decrypt:cipher_event"]


def test_bad_signature_is_audited_and_not_decrypted() -> None:
    audit = FakeAuditSink()
    decryptor = FakeDecryptor(_message_payload())
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


def test_replay_is_audited_by_timestamp_nonce_and_raw_hash() -> None:
    audit = FakeAuditSink()
    body = json.dumps(_message_payload()).encode()
    connector = FeishuConnector(
        project_memory_space_id="project_001",
        signing_secret=SECRET,
        audit_sink=audit,
    )
    headers = _signed_headers(body)

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
    body = json.dumps(_message_payload()).encode()
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
                headers=_signed_headers(body, timestamp=str(int(expired_at.timestamp()))),
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
            too_small.handle_webhook(headers=_signed_headers(body), body=body, received_at=RECEIVED_AT)
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
                headers=_signed_headers(encrypted_body),
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
                headers=_signed_headers(body),
                body=body,
                received_at=RECEIVED_AT,
            )
        )

    assert [record.reason_code for record in audit.records] == [
        "decrypt_failed",
        "schema_invalid",
    ]


def test_send_candidate_uses_push_sender_boundary() -> None:
    sender = FakePushSender()
    connector = FeishuConnector(project_memory_space_id="project_001", push_sender=sender)
    candidate = PushCandidate(
        id="push_001",
        platform_ref=PlatformRef(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="oc_group_001",
            thread_id="om_root",
            message_id=None,
        ),
        content="Review this candidate.",
        trace_id="trace_001",
    )

    result = asyncio.run(connector.send_candidate(candidate))

    assert result.delivered is True
    assert result.provider_message_id == "sent_001"
    assert sender.sent == [("oc_group_001", "Review this candidate.", "trace_001")]


def _message_payload() -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "event_001",
            "event_type": "im.message.receive_v1",
            "tenant_key": "tenant_001",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_001"}, "sender_name": "Ada"},
            "message": {
                "message_id": "om_001",
                "root_id": "om_root",
                "chat_id": "oc_group_001",
                "message_type": "text",
                "content": '{"text":"Remember encrypted events."}',
                "create_time": str(int(RECEIVED_AT.timestamp() * 1000)),
            },
        },
    }


def _signed_headers(body: bytes, *, timestamp: str | None = None) -> dict[str, str]:
    timestamp = timestamp or str(int(RECEIVED_AT.timestamp()))
    nonce = "nonce_001"
    return {
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": compute_feishu_signature(
            signing_secret=SECRET,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        ),
    }


class FakeAuditSink:
    def __init__(self) -> None:
        self.records: list[FeishuAuditRecord] = []

    def record(self, record: FeishuAuditRecord) -> None:
        self.records.append(record)


class FakeDecryptor:
    def __init__(self, payload: dict[str, object], calls: list[str] | None = None) -> None:
        self._payload = payload
        self.calls = calls if calls is not None else []

    def decrypt(self, encrypted_text: str) -> str:
        self.calls.append(f"decrypt:{encrypted_text}")
        return json.dumps(self._payload)


class FailingDecryptor:
    def decrypt(self, encrypted_text: str) -> str:
        raise ValueError(encrypted_text)


class RecordingReplayProtector:
    def __init__(self, calls: list[str]) -> None:
        self._seen: set[str] = set()
        self._calls = calls

    def mark_seen(self, replay_key: str) -> bool:
        self._calls.append("replay")
        if replay_key in self._seen:
            return False
        self._seen.add(replay_key)
        return True


class FakePushSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send_text(self, platform_ref: PlatformRef, content: str, trace_id: str) -> str:
        self.sent.append((platform_ref.channel_id, content, trace_id))
        return "sent_001"
