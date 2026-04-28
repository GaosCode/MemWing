from __future__ import annotations

import hmac
import inspect
import json
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from memwing.api.platform import (
    PlatformEvent,
    PlatformRawEvent,
    PlatformRawRequest,
    PlatformRef,
    PlatformSendResult,
    PushCandidate,
)
from memwing.api.types import JsonObject, JsonValue
from memwing.api.validation import SchemaValidationError, require_positive_int, require_text
from memwing.infrastructure.platforms.normalizer import (
    build_feishu_raw_event,
    normalize_feishu_event,
)
from memwing.infrastructure.platforms.feishu_security import (
    FeishuAuditRecord,
    FeishuAuditSink,
    FeishuConnectorError,
    FeishuReplayProtector,
    InMemoryFeishuReplayProtector,
    NoopFeishuAuditSink,
    compute_feishu_signature,
    has_formal_signature_headers,
    normalize_headers,
    parse_timestamp,
    payload_from_decrypted,
    raw_payload_hash,
    text_value,
    to_json_object,
)


FeishuWebhookKind = Literal["challenge", "event"]


class FeishuDecryptor(Protocol):
    def decrypt(self, encrypted_text: str) -> object:
        ...


class FeishuPushSender(Protocol):
    def send_text(
        self,
        platform_ref: PlatformRef,
        content: str,
        trace_id: str,
    ) -> str | Awaitable[str]:
        ...


@dataclass(frozen=True, slots=True)
class FeishuWebhookResult:
    kind: FeishuWebhookKind
    status_code: int
    body: JsonObject
    raw_payload_hash: str
    platform_event: PlatformEvent | None = None


class MockFeishuPushSender:
    def send_text(self, platform_ref: PlatformRef, content: str, trace_id: str) -> str:
        return f"mock-feishu:{platform_ref.channel_id}:{trace_id}"


class FeishuConnector:
    def __init__(
        self,
        *,
        project_memory_space_id: str,
        signing_secret: str | None = None,
        verification_token: str | None = None,
        max_body_bytes: int = 256 * 1024,
        max_timestamp_skew_seconds: int = 300,
        decryptor: FeishuDecryptor | None = None,
        replay_protector: FeishuReplayProtector | None = None,
        audit_sink: FeishuAuditSink | None = None,
        push_sender: FeishuPushSender | None = None,
    ) -> None:
        self._project_memory_space_id = require_text(
            project_memory_space_id,
            "project_memory_space_id",
        )
        self._signing_secret = signing_secret
        self._verification_token = verification_token
        self._max_body_bytes = require_positive_int(max_body_bytes, "max_body_bytes")
        self._max_timestamp_skew_seconds = require_positive_int(
            max_timestamp_skew_seconds,
            "max_timestamp_skew_seconds",
        )
        self._decryptor = decryptor
        self._replay_protector = replay_protector or InMemoryFeishuReplayProtector()
        self._audit_sink = audit_sink or NoopFeishuAuditSink()
        self._push_sender = push_sender or MockFeishuPushSender()

    async def handle_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        received_at: datetime | None = None,
    ) -> FeishuWebhookResult:
        received_at = received_at or datetime.now(tz=UTC)
        raw_hash = raw_payload_hash(body)
        if len(body) > self._max_body_bytes:
            await self._fail("body_too_large", raw_hash, 413)

        request_headers = normalize_headers(headers)
        payload = await self._parse_body(body, raw_hash)
        challenge = await self._challenge_from_payload(payload, request_headers, raw_hash)
        if challenge is not None:
            return FeishuWebhookResult(
                kind="challenge",
                status_code=200,
                body={"challenge": challenge},
                raw_payload_hash=raw_hash,
            )

        raw_request = PlatformRawRequest(
            platform="feishu",
            headers=request_headers,
            body=body,
            received_at=received_at,
            raw_payload_hash=raw_hash,
        )
        await self._verify_formal_request(raw_request)
        if "encrypt" in payload:
            payload = await self._decrypt_payload(payload["encrypt"], raw_hash)

        try:
            raw_event = build_feishu_raw_event(raw_request, payload)
            platform_event = await self.normalize_event(raw_event)
        except SchemaValidationError as exc:
            await self._fail(
                "schema_invalid",
                raw_hash,
                400,
                {"message": str(exc)},
            )

        return FeishuWebhookResult(
            kind="event",
            status_code=202,
            body={"ok": True, "raw_payload_hash": raw_hash},
            raw_payload_hash=raw_hash,
            platform_event=platform_event,
        )

    async def verify_request(self, raw_request: PlatformRawRequest) -> bool:
        try:
            await self._verify_formal_request(raw_request)
        except FeishuConnectorError:
            return False
        return True

    async def normalize_event(self, raw_event: PlatformRawEvent) -> PlatformEvent:
        return normalize_feishu_event(
            raw_event,
            project_memory_space_id=self._project_memory_space_id,
        )

    async def send_candidate(self, candidate: PushCandidate) -> PlatformSendResult:
        provider_message_id = self._push_sender.send_text(
            candidate.platform_ref,
            candidate.content,
            candidate.trace_id,
        )
        if inspect.isawaitable(provider_message_id):
            provider_message_id = await provider_message_id
        return PlatformSendResult(
            candidate_id=candidate.id,
            delivered=True,
            trace_id=candidate.trace_id,
            provider_message_id=provider_message_id,
        )

    async def _parse_body(self, body: bytes, raw_payload_hash: str) -> JsonObject:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            await self._fail(
                "schema_invalid",
                raw_payload_hash,
                400,
                {"message": f"invalid json: {exc.__class__.__name__}"},
            )
        if not isinstance(parsed, dict):
            await self._fail("schema_invalid", raw_payload_hash, 400, {"message": "body"})
        return to_json_object(parsed)

    async def _challenge_from_payload(
        self,
        payload: JsonObject,
        headers: Mapping[str, str],
        raw_payload_hash: str,
    ) -> str | None:
        challenge = text_value(payload.get("challenge"))
        if challenge is not None:
            await self._verify_challenge_token(payload, raw_payload_hash)
            return challenge

        encrypted_text = text_value(payload.get("encrypt"))
        if encrypted_text is None or has_formal_signature_headers(headers):
            return None

        decrypted_payload = await self._decrypt_payload(encrypted_text, raw_payload_hash)
        challenge = text_value(decrypted_payload.get("challenge"))
        if challenge is None:
            return None
        await self._verify_challenge_token(decrypted_payload, raw_payload_hash)
        return challenge

    async def _verify_challenge_token(
        self,
        payload: JsonObject,
        raw_payload_hash: str,
    ) -> None:
        if self._verification_token is None:
            return
        token = text_value(payload.get("token"))
        if not hmac.compare_digest(token or "", self._verification_token):
            await self._fail("challenge_token_invalid", raw_payload_hash, 401)

    async def _verify_formal_request(self, raw_request: PlatformRawRequest) -> None:
        raw_payload_hash = raw_request.raw_payload_hash
        if self._signing_secret is None or not self._signing_secret.strip():
            await self._fail("signature_secret_missing", raw_payload_hash, 401)

        timestamp = await self._required_header(
            raw_request,
            "x-lark-request-timestamp",
            "timestamp_missing",
        )
        nonce = await self._required_header(raw_request, "x-lark-request-nonce", "nonce_missing")
        signature = await self._required_header(
            raw_request,
            "x-lark-signature",
            "signature_missing",
        )
        request_timestamp = parse_timestamp(timestamp)
        if request_timestamp is None:
            await self._fail("timestamp_invalid", raw_payload_hash, 401)

        age_seconds = abs(raw_request.received_at.timestamp() - request_timestamp.timestamp())
        if age_seconds > self._max_timestamp_skew_seconds:
            await self._fail("timestamp_expired", raw_payload_hash, 401)

        expected = compute_feishu_signature(
            signing_secret=self._signing_secret or "",
            timestamp=timestamp,
            nonce=nonce,
            body=raw_request.body,
        )
        if not hmac.compare_digest(signature, expected):
            await self._fail("signature_mismatch", raw_payload_hash, 401)

        replay_key = f"{timestamp}:{nonce}:{raw_payload_hash}"
        if not self._replay_protector.mark_seen(replay_key):
            await self._fail("nonce_replayed", raw_payload_hash, 409)

    async def _required_header(
        self,
        raw_request: PlatformRawRequest,
        header_name: str,
        reason_code: str,
    ) -> str:
        value = text_value(raw_request.headers.get(header_name))
        if value is None:
            await self._fail(reason_code, raw_request.raw_payload_hash, 401)
        return value

    async def _decrypt_payload(self, encrypted_value: JsonValue, raw_payload_hash: str) -> JsonObject:
        encrypted_text = text_value(encrypted_value)
        if encrypted_text is None:
            await self._fail("decrypt_failed", raw_payload_hash, 400, {"message": "encrypt"})
        if self._decryptor is None:
            await self._fail("decryptor_missing", raw_payload_hash, 400)
        try:
            decrypted = self._decryptor.decrypt(encrypted_text or "")
            return payload_from_decrypted(decrypted)
        except Exception as exc:
            await self._fail(
                "decrypt_failed",
                raw_payload_hash,
                400,
                {"message": exc.__class__.__name__},
            )

    async def _fail(
        self,
        reason_code: str,
        raw_payload_hash: str,
        status_code: int,
        details: JsonObject | None = None,
    ) -> None:
        await self._audit_failure(reason_code, raw_payload_hash, status_code, details or {})
        raise FeishuConnectorError(reason_code, reason_code, status_code)

    async def _audit_failure(
        self,
        reason_code: str,
        raw_payload_hash: str,
        status_code: int,
        details: JsonObject,
    ) -> None:
        result = self._audit_sink.record(
            FeishuAuditRecord(
                reason_code=reason_code,
                raw_payload_hash=raw_payload_hash,
                status_code=status_code,
                details=details,
            )
        )
        if inspect.isawaitable(result):
            await result
