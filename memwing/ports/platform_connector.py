from __future__ import annotations

from typing import Protocol, runtime_checkable

from memwing.core.platform import (
    PlatformEvent,
    PlatformRawEvent,
    PlatformRawRequest,
    PlatformSendResult,
    PushCandidate,
)


@runtime_checkable
class PlatformConnectorPort(Protocol):
    async def verify_request(self, raw_request: PlatformRawRequest) -> bool:
        ...

    async def normalize_event(self, raw_event: PlatformRawEvent) -> PlatformEvent:
        ...

    async def send_candidate(self, candidate: PushCandidate) -> PlatformSendResult:
        ...
