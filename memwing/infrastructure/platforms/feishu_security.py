from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol

from memwing.api.types import JsonObject, JsonValue
from memwing.api.validation import SchemaValidationError, require_positive_int, require_text
from memwing.ports.platform_webhook import PlatformWebhookError


class FeishuAuditSink(Protocol):
    def record(self, record: "FeishuAuditRecord") -> object:
        ...


class FeishuReplayProtector(Protocol):
    def mark_seen(self, replay_key: str) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class FeishuAuditRecord:
    reason_code: str
    raw_payload_hash: str
    status_code: int
    outcome: Literal["failure", "success"] = "failure"
    details: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_code", require_text(self.reason_code, "reason_code"))
        object.__setattr__(
            self,
            "raw_payload_hash",
            require_text(self.raw_payload_hash, "raw_payload_hash"),
        )
        object.__setattr__(
            self,
            "status_code",
            require_positive_int(self.status_code, "status_code"),
        )


class FeishuConnectorError(PlatformWebhookError):
    def __init__(self, reason_code: str, message: str, status_code: int) -> None:
        super().__init__(reason_code, message, status_code)


class InMemoryFeishuReplayProtector:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def mark_seen(self, replay_key: str) -> bool:
        if replay_key in self._seen:
            return False
        self._seen.add(replay_key)
        return True


class NoopFeishuAuditSink:
    def record(self, record: FeishuAuditRecord) -> None:
        return None


def compute_feishu_signature(
    *,
    signing_secret: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    payload = timestamp.encode("utf-8") + nonce.encode("utf-8")
    payload += signing_secret.encode("utf-8") + body
    return sha256(payload).hexdigest()


def raw_payload_hash(body: bytes) -> str:
    return sha256(body).hexdigest()


def normalize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def has_formal_signature_headers(headers: Mapping[str, str]) -> bool:
    return all(
        text_value(headers.get(name)) is not None
        for name in (
            "x-lark-request-timestamp",
            "x-lark-request-nonce",
            "x-lark-signature",
        )
    )


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def payload_from_decrypted(decrypted: object) -> JsonObject:
    if isinstance(decrypted, bytes):
        decrypted = decrypted.decode("utf-8")
    if isinstance(decrypted, str):
        parsed = json.loads(decrypted)
    else:
        parsed = decrypted
    if not isinstance(parsed, dict):
        raise SchemaValidationError("decrypted payload must be an object")
    return to_json_object(parsed)


def to_json_object(mapping: dict[object, object]) -> JsonObject:
    return {str(key): to_json_value(value) for key, value in mapping.items()}


def to_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return tuple(to_json_value(item) for item in value)
    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}
    return str(value)


def text_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return None
