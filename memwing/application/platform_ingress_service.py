from __future__ import annotations

import inspect
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Protocol
import uuid

from memwing.application.remember_event_command import (
    RememberEventCommand,
    platform_event_to_remember_command,
)
from memwing.core.models import AuditEvent
from memwing.core.platform import PlatformEvent, PlatformRawEvent
from memwing.core.runtime import RememberEventResult
from memwing.ports.event_store import EventStoreUnitOfWorkPort


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
        audit_unit_of_work: EventStoreUnitOfWorkPort,
    ) -> None:
        self._normalizer = normalizer
        self._memory_gateway = memory_gateway
        self._audit_unit_of_work = audit_unit_of_work

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

    async def record_transport_failure(
        self,
        *,
        platform: str,
        reason_code: str,
        raw_payload_hash: str,
        status_code: int,
        received_at: datetime | None = None,
    ) -> None:
        now = received_at or datetime.now(UTC)
        trace_id = _new_trace_id()
        async with self._audit_unit_of_work.transaction() as tx:
            await tx.audit_events.record(
                AuditEvent(
                    id=_new_trace_id(),
                    trace_id=trace_id,
                    entity_type="platform_webhook",
                    entity_id=f"{platform}:{raw_payload_hash}",
                    stage="platform_webhook.rejected",
                    input_ref=raw_payload_hash,
                    output_ref=None,
                    decision="rejected",
                    reason_code=reason_code,
                    reason_text=f"status_code={status_code}",
                    source_event_ids=(),
                    latency_ms=None,
                    created_at=now,
                )
            )


def _new_trace_id() -> str:
    return str(uuid.uuid4())
