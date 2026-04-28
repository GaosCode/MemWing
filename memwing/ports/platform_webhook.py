from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from memwing.api.platform import PlatformEvent
from memwing.api.types import JsonObject
from memwing.api.validation import require_positive_int, require_text


PlatformWebhookKind = Literal["challenge", "event"]


@dataclass(frozen=True, slots=True)
class PlatformWebhookResult:
    kind: PlatformWebhookKind
    status_code: int
    body: JsonObject
    raw_payload_hash: str
    platform_event: PlatformEvent | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("challenge", "event"):
            raise ValueError("webhook kind is not supported")
        object.__setattr__(
            self,
            "status_code",
            require_positive_int(self.status_code, "status_code"),
        )
        object.__setattr__(
            self,
            "raw_payload_hash",
            require_text(self.raw_payload_hash, "raw_payload_hash"),
        )


class PlatformWebhookError(Exception):
    def __init__(self, reason_code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.reason_code = require_text(reason_code, "reason_code")
        self.status_code = require_positive_int(status_code, "status_code")


class PlatformWebhookHandlerPort(Protocol):
    async def handle_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        received_at: datetime | None = None,
    ) -> PlatformWebhookResult:
        ...
