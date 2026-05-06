from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import uuid

from memwing.application.failure_semantics import FailureClassification, classify_failure
from memwing.application.graph_write_processor import (
    GraphWriteBatchProcessingItemResult,
    GraphWriteProcessingResult,
    GraphWriteProcessor,
    GraphWriteProcessorInputError,
)
from memwing.core.errors import MemWingFailure
from memwing.core.models import AuditEvent, GraphWriteJob
from memwing.ports.event_store import EventStoreUnitOfWorkPort, OutboxLockOwnershipError
from memwing.ports.graph_backend import GraphBackendPort
from memwing.ports.lifecycle_transition import LifecycleTransitionPort


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GraphWriteWorkerResult:
    claimed: int
    succeeded: int
    retried: int
    dead_lettered: int


class GraphWriteWorker:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        graph_backend: GraphBackendPort,
        lifecycle_transition: LifecycleTransitionPort | None = None,
        worker_id: str,
        lock_duration: timedelta = timedelta(minutes=5),
        retry_delay: timedelta = timedelta(minutes=1),
        backend_timeout: timedelta = timedelta(seconds=900),
        batch_size: int = 1,
        max_project_concurrency: int = 1,
        max_global_concurrency: int = 16,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._graph_backend = graph_backend
        self._worker_id = worker_id
        self._lock_duration = lock_duration
        self._retry_delay = retry_delay
        self._batch_size = batch_size
        self._max_project_concurrency = max_project_concurrency
        self._max_global_concurrency = max_global_concurrency
        self._processor = GraphWriteProcessor(
            unit_of_work,
            graph_backend=graph_backend,
            lifecycle_transition=lifecycle_transition,
            worker_id=worker_id,
            lock_duration=lock_duration,
            backend_timeout=backend_timeout,
        )

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
        project_memory_space_id: str | None = None,
    ) -> GraphWriteWorkerResult:
        run_at = now or datetime.now(UTC)
        claim_limit = self._claim_limit(limit)
        async with self._unit_of_work.transaction() as tx:
            if project_memory_space_id is None:
                claimed = await tx.graph_write_jobs.claim_pending(
                    now=run_at,
                    worker_id=self._worker_id,
                    lock_duration=self._lock_duration,
                    limit=claim_limit,
                    max_project_concurrency=self._max_project_concurrency,
                )
            else:
                claimed = await tx.graph_write_jobs.claim_pending_for_project(
                    project_memory_space_id=project_memory_space_id,
                    now=run_at,
                    worker_id=self._worker_id,
                    lock_duration=self._lock_duration,
                    limit=claim_limit,
                    max_project_concurrency=self._max_project_concurrency,
                )

        succeeded = 0
        retried = 0
        dead_lettered = 0
        completion_at = now or datetime.now(UTC)
        for item in await self._processor.process_batch(claimed, now=completion_at):
            item_result = await self._record_batch_item(item=item, now=completion_at)
            succeeded += item_result.succeeded
            retried += item_result.retried
            dead_lettered += item_result.dead_lettered

        self._log_cache_metrics()
        return GraphWriteWorkerResult(
            claimed=len(claimed),
            succeeded=succeeded,
            retried=retried,
            dead_lettered=dead_lettered,
        )

    def _claim_limit(self, limit: int | None) -> int:
        requested = self._batch_size if limit is None else limit
        return max(0, min(requested, self._max_global_concurrency))

    def _log_cache_metrics(self) -> None:
        snapshot = _cache_metrics_snapshot(self._graph_backend)
        if not snapshot:
            return
        formatted = " ".join(f"{key}={snapshot[key]}" for key in sorted(snapshot))
        logger.info("graph_write.cache_metrics %s", formatted)

    async def _record_batch_item(
        self,
        *,
        item: GraphWriteBatchProcessingItemResult,
        now: datetime,
    ) -> GraphWriteWorkerResult:
        if item.error is None:
            if item.result is None:
                raise RuntimeError("graph batch item succeeded without a processing result")
            await self._record_success(job=item.job, processing_result=item.result, now=now)
            return GraphWriteWorkerResult(claimed=0, succeeded=1, retried=0, dead_lettered=0)

        if isinstance(item.error, OutboxLockOwnershipError):
            await self._record_lock_ownership_failure(job=item.job, exc=item.error, now=now)
            raise item.error

        failure = classify_failure(item.error, audit_stage="graph_write.failed")
        updated = await self._record_failure(
            job=item.job,
            error=_safe_error_summary(item.error),
            failure=failure,
            now=now,
        )
        if updated.status == "dead_letter":
            return GraphWriteWorkerResult(claimed=0, succeeded=0, retried=0, dead_lettered=1)
        return GraphWriteWorkerResult(claimed=0, succeeded=0, retried=1, dead_lettered=0)

    async def _record_success(
        self,
        *,
        job: GraphWriteJob,
        processing_result: GraphWriteProcessingResult,
        now: datetime,
    ) -> int:
        async with self._unit_of_work.transaction() as tx:
            updated = await tx.graph_write_jobs.mark_succeeded(
                job_id=job.id,
                locked_by=self._worker_id,
                now=now,
            )
            await tx.audit_events.record(
                _audit_event(
                    job=updated,
                    stage="graph_write.succeeded",
                    decision="succeeded",
                    output_ref=f"memory_graph_links:{processing_result.link_count}",
                    reason_text=None,
                    now=now,
                )
            )
            return processing_result.link_count

    async def _record_failure(
        self,
        *,
        job: GraphWriteJob,
        error: str,
        failure: FailureClassification,
        now: datetime,
    ) -> GraphWriteJob:
        async with self._unit_of_work.transaction() as tx:
            if failure.dead_letter and not failure.retryable:
                updated = await tx.graph_write_jobs.mark_dead_letter(
                    job_id=job.id,
                    locked_by=self._worker_id,
                    now=now,
                    error=error,
                )
            else:
                updated = await tx.graph_write_jobs.mark_failed(
                    job_id=job.id,
                    locked_by=self._worker_id,
                    now=now,
                    error=error,
                    retry_delay=self._retry_delay,
                )
            is_dead_letter = updated.status == "dead_letter"
            await tx.audit_events.record(
                _audit_event(
                    job=updated,
                    stage="graph_write.dead_letter" if is_dead_letter else "graph_write.retry",
                    decision="dead_letter" if is_dead_letter else "retry",
                    output_ref=updated.status,
                    reason_code=failure.reason_code,
                    reason_text=error,
                    now=now,
                )
            )
            return updated

    async def _record_lock_ownership_failure(
        self,
        *,
        job: GraphWriteJob,
        exc: OutboxLockOwnershipError,
        now: datetime,
    ) -> None:
        failure = classify_failure(exc, audit_stage="graph_write.lock_lost")
        async with self._unit_of_work.transaction() as tx:
            await tx.audit_events.record(
                _audit_event(
                    job=job,
                    stage="graph_write.lock_lost",
                    decision="aborted",
                    output_ref="lock_lost",
                    reason_code=failure.reason_code,
                    reason_text=_safe_error_summary(exc),
                    now=now,
                )
            )


def _safe_error_summary(exc: Exception) -> str:
    if isinstance(exc, GraphWriteProcessorInputError):
        return str(exc)
    if isinstance(exc, MemWingFailure) and exc.reason_code.startswith("graphiti_"):
        return exc.safe_message
    return exc.__class__.__name__


def _cache_metrics_snapshot(graph_backend: GraphBackendPort) -> dict[str, int]:
    snapshot = getattr(graph_backend, "cache_metrics_snapshot", None)
    if snapshot is None:
        return {}
    metrics = snapshot()
    if not isinstance(metrics, dict):
        return {}
    return {key: value for key, value in metrics.items() if isinstance(key, str) and isinstance(value, int)}


def _audit_event(
    *,
    job: GraphWriteJob,
    stage: str,
    decision: str,
    output_ref: str | None,
    reason_text: str | None,
    now: datetime,
    reason_code: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid4()),
        trace_id=f"graph_write:{job.id}",
        entity_type="graph_write_job",
        entity_id=job.id,
        stage=stage,
        input_ref=job.id,
        output_ref=output_ref,
        decision=decision,
        reason_code=reason_code,
        reason_text=reason_text,
        source_event_ids=job.source_event_ids,
        latency_ms=None,
        created_at=now,
    )
