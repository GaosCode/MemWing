from __future__ import annotations

from datetime import datetime
from typing import Callable

from memwing.application.gateway_service import DEFAULT_OUTBOX_JOB_TYPES
from memwing.application.remember_event_records import (
    RememberEventRecordFactory,
    SourceEventIdentity,
)
from memwing.application.scope_resolver import ResolvedScope
from memwing.core.models import SourceEvent
from memwing.core.runtime import RememberEventResult
from memwing.ports.event_store import EventStoreUnitOfWorkPort


class ControlManualMemoryServiceMixin:
    _unit_of_work: EventStoreUnitOfWorkPort
    _now: Callable[[], datetime]

    async def create_manual_memory(
        self,
        *,
        scope: ResolvedScope,
        title: str,
        content: str,
        source_url: str | None,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
    ) -> RememberEventResult:
        now = self._now()
        payload = {
            "source": "memwing_control_plane",
            "title": title,
            "content": content,
            "source_url": source_url,
            "reason": reason,
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
            "scope": {
                "project_memory_space_id": scope.effective_scope.project_memory_space_id,
                "group_id": scope.source_group_id,
                "thread_id": scope.thread_id,
                "shared_group_id": scope.shared_group_id,
            },
        }
        source_content = f"{title}\n\n{content}"
        dedupe_hash = SourceEventIdentity.dedupe_hash(payload)
        source_event = SourceEvent(
            id=SourceEventIdentity.deterministic_id(
                project_memory_space_id=scope.effective_scope.project_memory_space_id,
                dedupe_hash=dedupe_hash,
                runtime_event_idempotency_key=None,
            ),
            project_memory_space_id=scope.effective_scope.project_memory_space_id,
            group_id=scope.source_group_id,
            thread_id=scope.thread_id,
            shared_group_id=scope.shared_group_id,
            author_id=actor_id,
            author_name=None,
            source_type="control.manual_memory",
            content=source_content,
            content_preview=source_content[:240],
            source_url=source_url,
            event_time=now,
            raw_payload_hash=dedupe_hash,
            metadata={
                "source_ref": {"kind": "control", "actor_id": actor_id},
                "adapter_metadata": {"payload": payload},
            },
            purged_at=None,
            purged_by=None,
            purge_reason=None,
            purge_level="none",
            graph_backend_raw_retained=False,
            created_at=now,
            runtime_event_idempotency_key=None,
        )

        async with self._unit_of_work.transaction() as tx:
            stored_event, inserted = await tx.source_events.insert_if_absent(source_event)
            if not inserted:
                return RememberEventResult(
                    source_event_id=stored_event.id,
                    accepted=True,
                    trace_id=trace_id,
                    duplicate_of=stored_event.id,
                )

            plan = RememberEventRecordFactory().build_plan(
                source_event=stored_event,
                trace_id=trace_id,
                outbox_job_types=DEFAULT_OUTBOX_JOB_TYPES,
            )
            for audit_event in plan.audit_events:
                await tx.audit_events.record(audit_event)
            for job in plan.outbox_jobs:
                await tx.outbox_jobs.enqueue(job)

        return RememberEventResult(
            source_event_id=source_event.id,
            accepted=True,
            trace_id=trace_id,
        )
