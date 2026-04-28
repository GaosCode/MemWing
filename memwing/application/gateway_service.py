from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from memwing.api.agent_context import AgentRuntimeEvent, RememberEventResult
from memwing.api.platform import PlatformEvent
from memwing.core.models import SourceEvent
from memwing.core.scope import MemoryScope
from memwing.ports.event_store import EventStoreUnitOfWorkPort

from .remember_event_records import (
    capture_audit_event,
    outbox_job,
    rejected_audit_event,
    source_event_id,
)
from .scope_resolver import ScopeResolutionError, ScopeResolver


DEFAULT_OUTBOX_JOB_TYPES: Final[tuple[str, ...]] = (
    "evidence.index_source_event",
    "working_memory.append",
    "page_memory.maybe_rebuild",
    "long_term_filter.classify",
)


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

    async def remember_event(
        self,
        event: PlatformEvent | AgentRuntimeEvent,
    ) -> RememberEventResult:
        trace_id = _new_trace_id()
        try:
            normalized = await self._normalize_event(event)
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

            await tx.audit_events.record(
                capture_audit_event(
                    source_event=source_event,
                    trace_id=trace_id,
                    now=source_event.created_at,
                )
            )
            for job_type in self._outbox_job_types:
                await tx.outbox_jobs.enqueue(
                    outbox_job(
                        source_event=source_event,
                        job_type=job_type,
                        now=source_event.created_at,
                    )
                )

        return RememberEventResult(
            source_event_id=normalized.source_event.id,
            accepted=True,
            trace_id=trace_id,
        )

    async def _normalize_event(
        self,
        event: PlatformEvent | AgentRuntimeEvent,
    ) -> _NormalizedEvent:
        if isinstance(event, PlatformEvent):
            return await self._normalize_platform_event(event)
        return await self._normalize_runtime_event(event)

    async def _normalize_platform_event(
        self,
        event: PlatformEvent,
    ) -> _NormalizedEvent:
        scope_hint = MemoryScope(
            project_memory_space_id=event.project_memory_space_id,
            group_id=event.group_id,
            thread_id=event.thread_id,
            shared_group_id=event.shared_group_id,
        )
        resolved = await self._scope_resolver.resolve_platform(event.platform_ref, scope_hint)
        raw_payload_hash = _stable_hash(event.raw_payload)
        now = datetime.now(UTC)
        return _NormalizedEvent(
            source_event=SourceEvent(
                id=source_event_id(
                    project_memory_space_id=resolved.effective_scope.project_memory_space_id,
                    raw_payload_hash=raw_payload_hash,
                    runtime_event_idempotency_key=None,
                ),
                project_memory_space_id=resolved.effective_scope.project_memory_space_id,
                group_id=resolved.source_group_id,
                thread_id=resolved.thread_id,
                shared_group_id=resolved.shared_group_id,
                author_id=event.author_id,
                author_name=event.author_name,
                source_type=event.source_type,
                content=event.content,
                content_preview=_content_preview(event.content),
                source_url=event.source_url,
                event_time=event.event_time,
                raw_payload_hash=raw_payload_hash,
                metadata={
                    "source_ref_kind": "platform",
                    "platform": event.platform_ref.platform,
                    "tenant_id": event.platform_ref.tenant_id,
                    "channel_id": event.platform_ref.channel_id,
                    "message_id": event.platform_ref.message_id,
                    "raw_payload": event.raw_payload,
                },
                purged_at=None,
                purged_by=None,
                purge_reason=None,
                purge_level="none",
                graph_backend_raw_retained=False,
                created_at=now,
                runtime_event_idempotency_key=None,
            )
        )

    async def _normalize_runtime_event(
        self,
        event: AgentRuntimeEvent,
    ) -> _NormalizedEvent:
        if event.content is None:
            raise RememberEventError("AgentRuntimeEvent content is required for remember_event")

        resolved = await self._scope_resolver.resolve_runtime(event.runtime_ref, event.scope)
        raw_payload_hash = _stable_hash(
            {
                "runtime": event.runtime_ref.runtime,
                "agent_id": event.runtime_ref.agent_id,
                "workspace_id": event.runtime_ref.workspace_id,
                "session_id": event.runtime_ref.session_id,
                "run_id": event.run_id,
                "message_id": event.message_id,
                "tool_call_id": event.tool_call_id,
                "hook_name": event.hook_name,
                "sequence": event.sequence,
                "idempotency_key": event.idempotency_key,
                "event_type": event.event_type,
                "content": event.content,
                "payload": event.payload,
                "event_time": event.event_time.isoformat(),
            }
        )
        now = datetime.now(UTC)
        return _NormalizedEvent(
            source_event=SourceEvent(
                id=source_event_id(
                    project_memory_space_id=resolved.effective_scope.project_memory_space_id,
                    raw_payload_hash=raw_payload_hash,
                    runtime_event_idempotency_key=event.idempotency_key,
                ),
                project_memory_space_id=resolved.effective_scope.project_memory_space_id,
                group_id=resolved.source_group_id,
                thread_id=resolved.thread_id,
                shared_group_id=resolved.shared_group_id,
                author_id=None,
                author_name=None,
                source_type=f"agent_runtime.{event.event_type}",
                content=event.content,
                content_preview=_content_preview(event.content),
                source_url=None,
                event_time=event.event_time,
                raw_payload_hash=raw_payload_hash,
                metadata={
                    "source_ref_kind": "agent_runtime",
                    "runtime": event.runtime_ref.runtime,
                    "agent_id": event.runtime_ref.agent_id,
                    "workspace_id": event.runtime_ref.workspace_id,
                    "session_id": event.runtime_ref.session_id,
                    "run_id": event.run_id,
                    "message_id": event.message_id,
                    "hook_name": event.hook_name,
                    "event_type": event.event_type,
                    "payload": event.payload,
                },
                purged_at=None,
                purged_by=None,
                purge_reason=None,
                purge_level="none",
                graph_backend_raw_retained=False,
                created_at=now,
                runtime_event_idempotency_key=event.idempotency_key,
            )
        )


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _new_trace_id() -> str:
    return str(uuid.uuid4())


def _content_preview(content: str) -> str:
    return content[:240]
