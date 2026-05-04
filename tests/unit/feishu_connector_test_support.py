import json
from datetime import UTC, datetime

from memwing.api.platform import PlatformRef, PushCandidate
from memwing.core.types import JsonObject
from memwing.infrastructure.platforms.feishu_connector import (
    FeishuAuditRecord,
    compute_feishu_signature,
)


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
SECRET = "secret_001"


def build_message_payload() -> dict[str, object]:
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


def build_push_candidate() -> PushCandidate:
    return PushCandidate(
        id="push_001",
        platform_ref=PlatformRef(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="oc_group_001",
            thread_id="om_root",
            message_id=None,
        ),
        title="Memory review",
        kind="decision_card",
        content="Review this candidate.",
        trace_id="trace_001",
    )


def signed_headers(body: bytes, *, timestamp: str | None = None) -> dict[str, str]:
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
        self.sent: list[tuple[str, JsonObject, str]] = []

    def send_interactive_message(
        self,
        platform_ref: PlatformRef,
        payload: JsonObject,
        trace_id: str,
    ) -> str:
        self.sent.append((platform_ref.channel_id, payload, trace_id))
        return "sent_001"
