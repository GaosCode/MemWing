from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from memwing.application.long_term_filter_service import (
    LongTermFilterProcessCommand,
    LongTermFilterService,
)
from memwing.application.page_memory_policy import estimate_source_event_tokens
from memwing.application.remember_event_records import (
    long_term_filter_trigger_key_for_scope,
    page_memory_trigger_key_for_scope,
)
from memwing.core.models import OutboxJob, SourceEvent, WorkingMemoryEntry
from memwing.core.scope import EffectiveScope
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.workers.outbox_worker import OutboxWorker, OutboxWorkerResult
from memwing.workers.page_memory_worker import PageMemoryWorker


EVIDENCE_INDEX_JOB_TYPE = "evidence.index_source_event"
WORKING_MEMORY_APPEND_JOB_TYPE = "working_memory.append"
PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE = "page_memory.maybe_rebuild"
LONG_TERM_FILTER_CLASSIFY_JOB_TYPE = "long_term_filter.classify"


@dataclass(frozen=True, slots=True)
class DerivedOutboxWorkerResult:
    claimed: int
    succeeded: int
    retried: int
    dead_lettered: int
    evidence_indexed_source_events: int


class DerivedOutboxWorker:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        evidence_index: EvidenceIndexPort | None,
        long_term_filter: LongTermFilterService,
        page_memory_worker: PageMemoryWorker | None,
        worker_id: str,
        lock_duration: timedelta = timedelta(minutes=5),
        retry_delay: timedelta = timedelta(minutes=1),
        scope_job_limit: int = 40,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._evidence_index = evidence_index
        self._long_term_filter = long_term_filter
        self._page_memory_worker = page_memory_worker
        self._worker_id = worker_id
        self._lock_duration = lock_duration
        self._retry_delay = retry_delay
        self._scope_job_limit = scope_job_limit

    async def run_once(
        self,
        *,
        scope: EffectiveScope,
        now: datetime | None = None,
        event_job_limit: int = 10,
        job_types: tuple[str, ...] | None = None,
    ) -> DerivedOutboxWorkerResult:
        run_at = now or datetime.now(UTC)
        evidence_indexed_source_events = 0

        async def index_source_event(job: OutboxJob) -> None:
            nonlocal evidence_indexed_source_events
            await self._index_source_event(job)
            evidence_indexed_source_events += 1

        scope_level_handlers = _ScopeLevelHandlers(self, scope)
        outbox_worker = OutboxWorker(
            self._unit_of_work,
            worker_id=self._worker_id,
            handlers={
                EVIDENCE_INDEX_JOB_TYPE: index_source_event,
                WORKING_MEMORY_APPEND_JOB_TYPE: self._append_working_memory,
                PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE: scope_level_handlers.maybe_rebuild_page_memory,
                LONG_TERM_FILTER_CLASSIFY_JOB_TYPE: scope_level_handlers.classify_long_term,
            },
            lock_duration=self._lock_duration,
            retry_delay=self._retry_delay,
        )

        totals = _DerivedOutboxTotals()
        selected_job_types = set(job_types) if job_types is not None else None
        if selected_job_types is None or EVIDENCE_INDEX_JOB_TYPE in selected_job_types:
            evidence_result = await self._run_evidence_batch(
                outbox_worker=outbox_worker,
                scope=scope,
                now=run_at,
                limit=event_job_limit,
            )
            totals.add(evidence_result)
            evidence_indexed_source_events += evidence_result.evidence_indexed_source_events

        for job_type, limit, aggregate_key in (
            (WORKING_MEMORY_APPEND_JOB_TYPE, event_job_limit, None),
            (
                PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE,
                self._scope_job_limit,
                page_memory_trigger_key_for_scope(scope),
            ),
            (
                LONG_TERM_FILTER_CLASSIFY_JOB_TYPE,
                self._scope_job_limit,
                long_term_filter_trigger_key_for_scope(scope),
            ),
        ):
            if selected_job_types is not None and job_type not in selected_job_types:
                continue
            result = await outbox_worker.run_once(
                now=run_at,
                limit=limit,
                project_memory_space_id=scope.project_memory_space_id,
                job_type=job_type,
                aggregate_key=aggregate_key,
            )
            totals.add(result)

        return DerivedOutboxWorkerResult(
            claimed=totals.claimed,
            succeeded=totals.succeeded,
            retried=totals.retried,
            dead_lettered=totals.dead_lettered,
            evidence_indexed_source_events=evidence_indexed_source_events,
        )

    async def _run_evidence_batch(
        self,
        *,
        outbox_worker: OutboxWorker,
        scope: EffectiveScope,
        now: datetime,
        limit: int,
    ) -> DerivedOutboxWorkerResult:
        async with self._unit_of_work.transaction() as tx:
            claimed = await tx.outbox_jobs.claim_pending_for_project_and_type(
                project_memory_space_id=scope.project_memory_space_id,
                job_type=EVIDENCE_INDEX_JOB_TYPE,
                now=now,
                worker_id=self._worker_id,
                lock_duration=self._lock_duration,
                limit=limit,
            )
        if not claimed:
            return DerivedOutboxWorkerResult(
                claimed=0,
                succeeded=0,
                retried=0,
                dead_lettered=0,
                evidence_indexed_source_events=0,
            )

        try:
            await self._index_source_event_batch(claimed, scope)
        except Exception as exc:
            retried = 0
            dead_lettered = 0
            for job in claimed:
                updated = await outbox_worker.record_handler_failure(job=job, exc=exc, now=now)
                if updated.status == "dead_letter":
                    dead_lettered += 1
                else:
                    retried += 1
            return DerivedOutboxWorkerResult(
                claimed=len(claimed),
                succeeded=0,
                retried=retried,
                dead_lettered=dead_lettered,
                evidence_indexed_source_events=0,
            )

        for job in claimed:
            await outbox_worker.record_success(job=job, now=now)
        return DerivedOutboxWorkerResult(
            claimed=len(claimed),
            succeeded=len(claimed),
            retried=0,
            dead_lettered=0,
            evidence_indexed_source_events=len(claimed),
        )

    async def run_global_once(
        self,
        *,
        now: datetime | None = None,
        limit: int = 10,
        job_types: tuple[str, ...] | None = None,
    ) -> DerivedOutboxWorkerResult:
        run_at = now or datetime.now(UTC)
        evidence_indexed_source_events = 0

        async def index_source_event(job: OutboxJob) -> None:
            nonlocal evidence_indexed_source_events
            await self._index_source_event(job)
            evidence_indexed_source_events += 1

        scope_level_handlers = _GlobalScopeLevelHandlers(self)
        outbox_worker = OutboxWorker(
            self._unit_of_work,
            worker_id=self._worker_id,
            handlers={
                EVIDENCE_INDEX_JOB_TYPE: index_source_event,
                WORKING_MEMORY_APPEND_JOB_TYPE: self._append_working_memory,
                PAGE_MEMORY_MAYBE_REBUILD_JOB_TYPE: scope_level_handlers.maybe_rebuild_page_memory,
                LONG_TERM_FILTER_CLASSIFY_JOB_TYPE: scope_level_handlers.classify_long_term,
            },
            lock_duration=self._lock_duration,
            retry_delay=self._retry_delay,
        )
        result = await outbox_worker.run_once(now=run_at, limit=limit, job_types=job_types)
        return DerivedOutboxWorkerResult(
            claimed=result.claimed,
            succeeded=result.succeeded,
            retried=result.retried,
            dead_lettered=result.dead_lettered,
            evidence_indexed_source_events=evidence_indexed_source_events,
        )

    async def _index_source_event(self, job: OutboxJob) -> None:
        if self._evidence_index is None:
            raise RuntimeError("evidence index backend is not configured")
        source_event = await self._load_source_event(job.source_event_id)
        await self._evidence_index.index_source_event(
            source_event,
            _scope_from_source_event(source_event),
        )

    async def _index_source_event_batch(
        self,
        jobs: tuple[OutboxJob, ...],
        scope: EffectiveScope,
    ) -> None:
        if self._evidence_index is None:
            raise RuntimeError("evidence index backend is not configured")
        source_events = tuple([await self._load_source_event(job.source_event_id) for job in jobs])
        index_source_events = getattr(self._evidence_index, "index_source_events", None)
        if index_source_events is None:
            for source_event in source_events:
                await self._evidence_index.index_source_event(source_event, scope)
            return
        await index_source_events(source_events, scope)

    async def _append_working_memory(self, job: OutboxJob) -> None:
        source_event = await self._load_source_event(job.source_event_id)
        async with self._unit_of_work.transaction() as tx:
            sequence = await tx.working_memory_entries.next_sequence(
                project_memory_space_id=source_event.project_memory_space_id,
                thread_id=source_event.thread_id,
            )
            await tx.working_memory_entries.append(
                WorkingMemoryEntry(
                    id=_uuid("working_memory", source_event.id),
                    source_event_id=source_event.id,
                    project_memory_space_id=source_event.project_memory_space_id,
                    group_id=source_event.group_id,
                    thread_id=source_event.thread_id,
                    shared_group_id=source_event.shared_group_id,
                    content=source_event.content,
                    token_count=estimate_source_event_tokens(source_event),
                    sequence=sequence,
                    flushed_at=None,
                    created_at=datetime.now(UTC),
                )
            )

    async def _maybe_rebuild_page_memory(self, job: OutboxJob) -> None:
        if self._page_memory_worker is None:
            raise RuntimeError("page memory worker is not configured")
        await self._page_memory_worker.maybe_rebuild(job)

    async def _classify_long_term(self, job: OutboxJob, scope: EffectiveScope) -> None:
        await self._long_term_filter.process_scope(
            LongTermFilterProcessCommand(
                scope=scope,
                now=datetime.now(UTC),
                trace_id=f"long_term_filter:{job.id}",
            )
        )

    async def _load_source_event(self, source_event_id: str) -> SourceEvent:
        async with self._unit_of_work.transaction() as tx:
            source_event = await tx.source_events.get_source_event(source_event_id)
        if source_event is None:
            raise RuntimeError("source event for outbox job was not found")
        return source_event


class _ScopeLevelHandlers:
    def __init__(self, worker: DerivedOutboxWorker, scope: EffectiveScope) -> None:
        self._worker = worker
        self._scope = scope
        self._page_memory_rebuilt = False
        self._long_term_filter_classified = False

    async def maybe_rebuild_page_memory(self, job: OutboxJob) -> None:
        if self._page_memory_rebuilt:
            return
        await self._worker._maybe_rebuild_page_memory(job)
        self._page_memory_rebuilt = True

    async def classify_long_term(self, job: OutboxJob) -> None:
        if self._long_term_filter_classified:
            return
        await self._worker._classify_long_term(job, self._scope)
        self._long_term_filter_classified = True


class _GlobalScopeLevelHandlers:
    def __init__(self, worker: DerivedOutboxWorker) -> None:
        self._worker = worker
        self._processed_page_memory_aggregates: set[str] = set()
        self._processed_long_term_filter_aggregates: set[str] = set()

    async def maybe_rebuild_page_memory(self, job: OutboxJob) -> None:
        aggregate_key = _required_aggregate_key(job)
        if aggregate_key in self._processed_page_memory_aggregates:
            return
        await self._worker._maybe_rebuild_page_memory(job)
        self._processed_page_memory_aggregates.add(aggregate_key)

    async def classify_long_term(self, job: OutboxJob) -> None:
        aggregate_key = _required_aggregate_key(job)
        if aggregate_key in self._processed_long_term_filter_aggregates:
            return
        source_event = await self._worker._load_source_event(job.source_event_id)
        await self._worker._classify_long_term(job, _scope_from_source_event(source_event))
        self._processed_long_term_filter_aggregates.add(aggregate_key)


@dataclass(slots=True)
class _DerivedOutboxTotals:
    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead_lettered: int = 0

    def add(self, result: OutboxWorkerResult) -> None:
        self.claimed += result.claimed
        self.succeeded += result.succeeded
        self.retried += result.retried
        self.dead_lettered += result.dead_lettered


def _scope_from_source_event(source_event: SourceEvent) -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id=source_event.project_memory_space_id,
        group_ids=(source_event.group_id,) if source_event.group_id is not None else None,
        thread_id=source_event.thread_id,
        shared_group_id=source_event.shared_group_id,
        safe_mode_enabled=source_event.group_id is not None,
        cross_group_allowed=source_event.group_id is None,
    )


def _uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))


def _required_aggregate_key(job: OutboxJob) -> str:
    if job.aggregate_key is None:
        raise RuntimeError("scope-level outbox job requires aggregate_key")
    return job.aggregate_key
