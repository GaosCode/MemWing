from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import Protocol

from memwing.api.agent_runtime import RememberEventResult
from memwing.api.platform import PlatformEvent, PlatformRawEvent
from memwing.application.remember_event_command import (
    RememberEventCommand,
    platform_event_to_remember_command,
)


class PlatformEventNormalizer(Protocol):
    def normalize_event(self, raw_event: PlatformRawEvent) -> PlatformEvent | Awaitable[PlatformEvent]:
        ...


class RememberEventGateway(Protocol):
    def remember_event(
        self,
        command: RememberEventCommand,
    ) -> RememberEventResult | Awaitable[RememberEventResult]:
        ...


class PlatformIngressService:
    def __init__(
        self,
        *,
        normalizer: PlatformEventNormalizer,
        memory_gateway: RememberEventGateway,
    ) -> None:
        self._normalizer = normalizer
        self._memory_gateway = memory_gateway

    async def ingest(self, raw_event: PlatformRawEvent) -> RememberEventResult:
        platform_event = self._normalizer.normalize_event(raw_event)
        if inspect.isawaitable(platform_event):
            platform_event = await platform_event
        remembered = self._memory_gateway.remember_event(
            platform_event_to_remember_command(platform_event)
        )
        if inspect.isawaitable(remembered):
            remembered = await remembered
        return remembered
