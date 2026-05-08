from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from memwing.application.outbox_job_catalog import source_event_job_types
from memwing.application.remember_event_command import RememberEventCommand
from memwing.core.models import SourceEvent
from memwing.core.runtime import RememberEventResult
from memwing.ports.event_store import EventStoreUnitOfWorkPort

from .remember_event_records import (
    RememberEventRecordFactory,
    SourceEventNormalizer,
    rejected_audit_event,
)
from .scope_resolver import ScopeResolutionError, ScopeResolver


DEFAULT_OUTBOX_JOB_TYPES = source_event_job_types()


class RememberEventError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _NormalizedEvent:
    source_event: SourceEvent


class MemoryGateway:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        scope_resolver: ScopeResolver,
        *,
        outbox_job_types: tuple[str, ...] = DEFAULT_OUTBOX_JOB_TYPES,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._scope_resolver = scope_resolver
        self._outbox_job_types = outbox_job_types
        self._normalizer = SourceEventNormalizer()
        self._record_factory = RememberEventRecordFactory()

    async def remember_event(
        self,
        command: RememberEventCommand,
    ) -> RememberEventResult:
        if not isinstance(command, RememberEventCommand):
            raise TypeError("MemoryGateway.remember_event requires RememberEventCommand")

        trace_id = _new_trace_id()
        try:
            normalized = await self._normalize_event(command)
        except ScopeResolutionError as exc:
            async with self._unit_of_work.transaction() as tx:
                await tx.audit_events.record(
                    rejected_audit_event(
                        trace_id=trace_id,
                        reason_text=str(exc),
                        now=datetime.now(UTC),
                    )
                )
            raise

        async with self._unit_of_work.transaction() as tx:
            source_event, inserted = await tx.source_events.insert_if_absent(
                normalized.source_event
            )
            if not inserted:
                return RememberEventResult(
                    source_event_id=source_event.id,
                    accepted=True,
                    trace_id=trace_id,
                    duplicate_of=source_event.id,
                )

            plan = self._record_factory.build_plan(
                source_event=source_event,
                trace_id=trace_id,
                outbox_job_types=self._outbox_job_types,
            )
            for audit_event in plan.audit_events:
                await tx.audit_events.record(audit_event)
            for job in plan.outbox_jobs:
                await tx.outbox_jobs.enqueue(job)

        return RememberEventResult(
            source_event_id=normalized.source_event.id,
            accepted=True,
            trace_id=trace_id,
        )

    async def _normalize_event(
        self,
        command: RememberEventCommand,
    ) -> _NormalizedEvent:
        if command.source_ref.kind == "platform":
            if command.source_ref.platform_ref is None:
                raise RememberEventError("platform source_ref is required for remember_event")
            resolved = await self._scope_resolver.resolve_platform(
                command.source_ref.platform_ref,
                command.scope_hint,
            )
        else:
            if command.source_ref.runtime_ref is None:
                raise RememberEventError("runtime source_ref is required for remember_event")
            resolved = await self._scope_resolver.resolve_runtime(
                command.source_ref.runtime_ref,
                command.scope_hint,
            )
        now = datetime.now(UTC)
        return _NormalizedEvent(
            source_event=self._normalizer.normalize(command, resolved, now=now)
        )


def _new_trace_id() -> str:
    return str(uuid.uuid4())
