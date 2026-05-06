from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from time import perf_counter
import uuid

from memwing.core.lifecycle import LifecycleAction
from memwing.core.errors import ProviderPermanentFailure, ProviderTransientFailure
from memwing.core.models import (
    AuditEvent,
    GraphFact,
    GraphWriteJob,
    GraphWriteResult,
    MemoryGraphLink,
    MemoryGraphLinkType,
)
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import (
    GraphBackendPort,
    GraphWriteBatchItemResult,
    GraphWriteBatchRequest,
    GraphWriteRequest,
)
from memwing.ports.lifecycle_transition import LifecycleTransitionPort, LifecycleTransitionRequest


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_handler)
logger.propagate = False


@dataclass(frozen=True, slots=True)
class GraphWriteProcessingResult:
    link_count: int
    invalidated_memory_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GraphWriteBatchProcessingItemResult:
    job: GraphWriteJob
    result: GraphWriteProcessingResult | None
    error: Exception | None


class GraphWriteProcessor:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        graph_backend: GraphBackendPort,
        lifecycle_transition: LifecycleTransitionPort | None,
        worker_id: str,
        lock_duration: timedelta,
        backend_timeout: timedelta,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._graph_backend = graph_backend
        self._lifecycle_transition = lifecycle_transition
        self._worker_id = worker_id
        self._lock_duration = lock_duration
        self._backend_timeout = backend_timeout

    async def process(
        self,
        job: GraphWriteJob,
        *,
        now: datetime,
    ) -> GraphWriteProcessingResult:
        request = await self._build_request(job)
        graph_result = await asyncio.wait_for(
            self._graph_backend.ingest_graph_job(request),
            timeout=self._backend_timeout.total_seconds(),
        )
        return await self._complete_graph_result(
            job=job,
            graph_result=graph_result,
            now=now,
        )

    async def process_batch(
        self,
        jobs: tuple[GraphWriteJob, ...],
        *,
        now: datetime,
    ) -> tuple[GraphWriteBatchProcessingItemResult, ...]:
        if not jobs:
            return ()

        batch_started = perf_counter()
        logger.info(
            "graph_write.processor.batch_started job_count=%s project_memory_space_id=%s",
            len(jobs),
            jobs[0].project_memory_space_id,
        )
        build_results: list[GraphWriteBatchProcessingItemResult] = []
        requests: list[GraphWriteRequest] = []
        for job in jobs:
            build_started = perf_counter()
            try:
                requests.append(await self._build_request(job))
            except GraphWriteProcessorInputError as exc:
                logger.info(
                    "graph_write.processor.build_failed job_id=%s memory_id=%s duration_ms=%.1f "
                    "error=%s",
                    job.id,
                    job.memory_id,
                    _elapsed_ms(build_started),
                    exc,
                )
                build_results.append(
                    GraphWriteBatchProcessingItemResult(job=job, result=None, error=exc)
                )
            else:
                logger.info(
                    "graph_write.processor.build_completed job_id=%s memory_id=%s "
                    "source_event_count=%s duration_ms=%.1f",
                    job.id,
                    job.memory_id,
                    len(job.source_event_ids),
                    _elapsed_ms(build_started),
                )

        if not requests:
            return tuple(build_results)

        await self._record_backend_started(requests, now=now)
        backend_started = perf_counter()
        logger.info(
            "graph_write.processor.backend_batch_started job_count=%s project_memory_space_id=%s "
            "serialization_key=%s timeout_seconds=%.1f",
            len(requests),
            requests[0].job.project_memory_space_id,
            requests[0].job.serialization_key,
            self._backend_timeout.total_seconds(),
        )
        try:
            batch_result = await asyncio.wait_for(
                self._graph_backend.ingest_graph_jobs(
                    GraphWriteBatchRequest(requests=tuple(requests))
                ),
                timeout=self._backend_timeout.total_seconds(),
            )
        except Exception as exc:
            logger.info(
                "graph_write.processor.backend_batch_failed job_count=%s duration_ms=%.1f "
                "error_type=%s",
                len(requests),
                _elapsed_ms(backend_started),
                exc.__class__.__name__,
            )
            return (
                *build_results,
                *(
                    GraphWriteBatchProcessingItemResult(
                        job=request.job,
                        result=None,
                        error=exc,
                    )
                    for request in requests
                ),
            )
        logger.info(
            "graph_write.processor.backend_batch_completed job_count=%s item_count=%s "
            "duration_ms=%.1f",
            len(requests),
            len(batch_result.items),
            _elapsed_ms(backend_started),
        )

        result_by_job_id = {item.job_id: item for item in batch_result.items}
        processed: list[GraphWriteBatchProcessingItemResult] = [*build_results]
        for request in requests:
            complete_started = perf_counter()
            item = result_by_job_id.get(request.job.id)
            if item is None:
                processed.append(
                    GraphWriteBatchProcessingItemResult(
                        job=request.job,
                        result=None,
                        error=GraphWriteProcessorInputError(
                            f"missing graph batch result for job {request.job.id}"
                        ),
                    )
                )
                continue
            if item.result is None:
                processed.append(
                    GraphWriteBatchProcessingItemResult(
                        job=request.job,
                        result=None,
                        error=_batch_item_error(item),
                    )
                )
                continue
            try:
                processing_result = await self._complete_graph_result(
                    job=request.job,
                    graph_result=item.result,
                    now=now,
                )
            except Exception as exc:
                logger.info(
                    "graph_write.processor.complete_failed job_id=%s duration_ms=%.1f "
                    "error_type=%s",
                    request.job.id,
                    _elapsed_ms(complete_started),
                    exc.__class__.__name__,
                )
                processed.append(
                    GraphWriteBatchProcessingItemResult(
                        job=request.job,
                        result=None,
                        error=exc,
                    )
                )
            else:
                logger.info(
                    "graph_write.processor.complete_completed job_id=%s link_count=%s "
                    "invalidated_memory_count=%s duration_ms=%.1f",
                    request.job.id,
                    processing_result.link_count,
                    len(processing_result.invalidated_memory_ids),
                    _elapsed_ms(complete_started),
                )
                processed.append(
                    GraphWriteBatchProcessingItemResult(
                        job=request.job,
                        result=processing_result,
                        error=None,
                    )
                )
        logger.info(
            "graph_write.processor.batch_completed job_count=%s processed_count=%s duration_ms=%.1f",
            len(jobs),
            len(processed),
            _elapsed_ms(batch_started),
        )
        return tuple(processed)

    async def _record_backend_started(
        self,
        requests: list[GraphWriteRequest],
        *,
        now: datetime,
    ) -> None:
        async with self._unit_of_work.transaction() as tx:
            for request in requests:
                await tx.audit_events.record(
                    AuditEvent(
                        id=str(uuid.uuid4()),
                        trace_id=f"graph_write:{request.job.id}",
                        entity_type="graph_write_job",
                        entity_id=request.job.id,
                        stage="graph_write.backend.started",
                        input_ref=request.job.id,
                        output_ref="graph_backend.ingest_graph_jobs",
                        decision="started",
                        reason_code=None,
                        reason_text=(
                            f"batch_size={len(requests)} serialization_key="
                            f"{request.job.serialization_key}"
                        ),
                        source_event_ids=request.job.source_event_ids,
                        latency_ms=None,
                        created_at=now,
                    )
                )

    async def _complete_graph_result(
        self,
        *,
        job: GraphWriteJob,
        graph_result: GraphWriteResult,
        now: datetime,
    ) -> GraphWriteProcessingResult:
        self._ensure_lifecycle_port_for_invalidated_facts(graph_result.invalidated_facts)
        invalidated_memory_ids = await self._memory_ids_for_invalidated_facts(
            facts=graph_result.invalidated_facts,
            project_memory_space_id=job.project_memory_space_id,
        )
        await self._mark_invalidated_memories_needs_review(
            job=job,
            memory_ids=invalidated_memory_ids,
            now=now,
        )
        link_count = await self._write_graph_links_under_current_lock(
            job=job,
            graph_result=graph_result,
            now=now,
        )
        return GraphWriteProcessingResult(
            link_count=link_count,
            invalidated_memory_ids=invalidated_memory_ids,
        )

    async def _build_request(self, job: GraphWriteJob) -> GraphWriteRequest:
        async with self._unit_of_work.transaction() as tx:
            memory_item = await tx.memory_items.get(job.memory_id)
            if memory_item is None:
                raise GraphWriteProcessorInputError(f"missing memory item {job.memory_id}")

            source_events = []
            for source_event_id in job.source_event_ids:
                source_event = await tx.source_events.get_source_event(source_event_id)
                if source_event is None:
                    raise GraphWriteProcessorInputError(f"missing source event {source_event_id}")
                source_events.append(source_event)

        return GraphWriteRequest(
            job=job,
            memory_item=memory_item,
            source_events=tuple(source_events),
        )

    async def _write_graph_links_under_current_lock(
        self,
        *,
        job: GraphWriteJob,
        graph_result: GraphWriteResult,
        now: datetime,
    ) -> int:
        async with self._unit_of_work.transaction() as tx:
            await tx.graph_write_jobs.extend_lock(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
                lock_duration=self._lock_duration,
            )
            link_count = 0
            for episode_ref in graph_result.backend_episode_refs:
                await tx.memory_graph_links.upsert(
                    _memory_graph_link(
                        job=job,
                        source_event_id=job.source_event_ids[0],
                        backend=graph_result.backend,
                        backend_object_type="episode",
                        backend_object_id=episode_ref,
                        link_type="episode",
                        now=now,
                    )
                )
                link_count += 1

            for fact in graph_result.facts:
                if not fact.source_event_ids:
                    raise GraphWriteProcessorInputError("graph fact missing source event ids")
                source_event_id = fact.source_event_ids[0]
                await tx.memory_graph_links.upsert(
                    _memory_graph_link(
                        job=job,
                        source_event_id=source_event_id,
                        backend=graph_result.backend,
                        backend_object_type="fact",
                        backend_object_id=fact.fact_id,
                        link_type="fact",
                        now=now,
                    )
                )
                link_count += 1
            return link_count

    async def _extend_current_lock(
        self,
        *,
        job: GraphWriteJob,
        now: datetime,
    ) -> None:
        async with self._unit_of_work.transaction() as tx:
            await tx.graph_write_jobs.extend_lock(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
                lock_duration=self._lock_duration,
            )

    async def _memory_ids_for_invalidated_facts(
        self,
        *,
        facts: tuple[GraphFact, ...],
        project_memory_space_id: str,
    ) -> tuple[str, ...]:
        memory_ids: list[str] = []
        seen: set[str] = set()
        async with self._unit_of_work.transaction() as tx:
            for fact in facts:
                if not fact.source_event_ids:
                    raise GraphWriteProcessorInputError(
                        "invalidated graph fact missing source event ids"
                    )
                for source_event_id in fact.source_event_ids:
                    for item in await tx.memory_items.list_by_source_event(source_event_id):
                        if item.project_memory_space_id != project_memory_space_id:
                            continue
                        if item.id in seen:
                            continue
                        seen.add(item.id)
                        memory_ids.append(item.id)
        return tuple(memory_ids)

    def _ensure_lifecycle_port_for_invalidated_facts(
        self,
        facts: tuple[GraphFact, ...],
    ) -> None:
        if facts and self._lifecycle_transition is None:
            raise GraphWriteProcessorInputError(
                "lifecycle transition port required for graph invalidations"
            )

    async def _mark_invalidated_memories_needs_review(
        self,
        *,
        job: GraphWriteJob,
        memory_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        if not memory_ids:
            return
        if self._lifecycle_transition is None:
            raise GraphWriteProcessorInputError(
                "lifecycle transition port required for graph invalidations"
            )

        for memory_id in memory_ids:
            await self._extend_current_lock(job=job, now=now)
            await self._lifecycle_transition.transition(
                LifecycleTransitionRequest(
                    memory_id=memory_id,
                    action=LifecycleAction.MARK_NEEDS_REVIEW,
                    actor_id="graph_write_worker",
                    reason="graph fact invalidated",
                    idempotency_key=f"graph:{job.id}:invalidated:{memory_id}",
                    trace_id=f"graph_write:{job.id}",
                    now=now,
                )
            )


class GraphWriteProcessorInputError(RuntimeError):
    pass


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def _batch_item_error(item: GraphWriteBatchItemResult) -> Exception:
    reason_code = item.reason_code or "graph_batch_item_failed"
    safe_message = item.error_message or item.error_type or reason_code
    failure_type = ProviderTransientFailure if item.retryable else ProviderPermanentFailure
    return failure_type(reason_code, safe_message)


def _memory_graph_link(
    *,
    job: GraphWriteJob,
    source_event_id: str,
    backend: str,
    backend_object_type: str,
    backend_object_id: str,
    link_type: MemoryGraphLinkType,
    now: datetime,
) -> MemoryGraphLink:
    return MemoryGraphLink(
        id=str(uuid.uuid4()),
        backend=backend,
        memory_id=job.memory_id,
        source_event_id=source_event_id,
        project_memory_space_id=job.project_memory_space_id,
        backend_space_id=job.project_memory_space_id,
        backend_object_type=backend_object_type,
        backend_object_id=backend_object_id,
        link_type=link_type,
        created_at=now,
    )
