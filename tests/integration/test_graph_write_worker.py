import asyncio
from dataclasses import replace
from datetime import timedelta
import logging

import pytest

from memwing.core.models import GraphWriteJob, GraphWriteResult, SourceEvent
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.event_store import OutboxLockOwnershipError
from memwing.ports.graph_backend import (
    GraphWriteBatchItemResult,
    GraphWriteBatchRequest,
    GraphWriteBatchResult,
    GraphWriteRequest,
)
from memwing.workers.graph_write_worker import GraphWriteWorker
from tests.integration.graph_write_worker_fixtures import (
    FakeGraphBackend,
    NOW,
    graph_job,
    memory_item,
    source_event,
    successful_graph_result,
)


def test_graph_write_worker_ingests_job_writes_links_and_audit() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job())

        backend = FakeGraphBackend(successful_graph_result())
        worker = GraphWriteWorker(
            store,
            graph_backend=backend,
            worker_id="graph_worker_001",
        )

        result = await worker.run_once(now=NOW)

        async with store.transaction() as tx:
            links = await tx.memory_graph_links.list_by_memory("memory_001")

        assert result.claimed == 1
        assert result.succeeded == 1
        assert backend.requests == (
            GraphWriteRequest(
                job=graph_job(
                    status="processing",
                    locked_by="graph_worker_001",
                    locked_at=NOW,
                    lock_expires_at=NOW + timedelta(minutes=5),
                    updated_at=NOW,
                ),
                memory_item=memory_item(),
                source_events=(source_event(),),
            ),
        )
        assert len(links) == 2
        assert {link.backend_object_id for link in links} == {"episode_001", "fact_001"}
        assert {link.link_type for link in links} == {"episode", "fact"}
        assert store.audit_events[-1].stage == "graph_write.succeeded"
        assert store.audit_events[-1].input_ref == "graph_job_001"
        assert store.audit_events[-1].output_ref == "memory_graph_links:2"
        assert "Decision source text." not in (store.audit_events[-1].reason_text or "")

    asyncio.run(scenario())


def test_graph_write_worker_logs_model_cache_metrics(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryDataStore()

    class MetricsGraphBackend(FakeGraphBackend):
        def cache_metrics_snapshot(self) -> dict[str, int]:
            return {
                "embedding_hits": 2,
                "embedding_misses": 1,
                "llm_hits": 1,
                "llm_provider_calls": 1,
            }

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job())

        backend = MetricsGraphBackend(successful_graph_result())
        worker = GraphWriteWorker(
            store,
            graph_backend=backend,
            worker_id="graph_worker_001",
        )

        with caplog.at_level(logging.INFO, logger="memwing.workers.graph_write_worker"):
            await worker.run_once(now=NOW)

    asyncio.run(scenario())

    assert "graph_write.cache_metrics" in caplog.text
    assert "embedding_hits=2" in caplog.text
    assert "llm_provider_calls=1" in caplog.text


def test_graph_write_worker_processes_same_serialization_key_batch() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        second_source = replace(
            source_event(),
            id="source_002",
            raw_payload_hash="hash_002",
            runtime_event_idempotency_key="runtime-key-002",
        )
        second_memory = replace(
            memory_item(),
            id="memory_002",
            source_event_ids=("source_002",),
            primary_source_event_id="source_002",
        )
        second_job = replace(
            graph_job(),
            id="graph_job_002",
            memory_id="memory_002",
            source_event_ids=("source_002",),
            idempotency_key="graph:memory_002",
        )
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.source_events.insert_if_absent(second_source)
            await tx.memory_items.upsert(memory_item())
            await tx.memory_items.upsert(second_memory)
            await tx.graph_write_jobs.enqueue(graph_job())
            await tx.graph_write_jobs.enqueue(second_job)

        backend = FakeGraphBackend(successful_graph_result())
        worker = GraphWriteWorker(
            store,
            graph_backend=backend,
            worker_id="graph_worker_001",
            batch_size=8,
        )

        result = await worker.run_once(now=NOW)

        assert result.claimed == 2
        assert result.succeeded == 2
        assert result.retried == 0
        assert result.dead_lettered == 0
        assert tuple(request.job.id for request in backend.requests) == (
            "graph_job_001",
            "graph_job_002",
        )
        assert [event.stage for event in store.audit_events[-2:]] == [
            "graph_write.succeeded",
            "graph_write.succeeded",
        ]

    asyncio.run(scenario())


def test_graph_write_worker_records_mixed_batch_outcomes_without_rolling_back_successes() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        jobs = (
            _derived_job("graph_job_success", "memory_success", "source_success", order=0),
            _derived_job("graph_job_retry", "memory_retry", "source_retry", order=1),
            _derived_job("graph_job_dead", "memory_dead", "source_dead", max_attempts=1, order=2),
            _derived_job("graph_job_lock_lost", "memory_lock_lost", "source_lock_lost", order=3),
        )
        async with store.transaction() as tx:
            for job in jobs:
                await tx.source_events.insert_if_absent(_derived_source_event(job.source_event_ids[0]))
                await tx.memory_items.upsert(
                    replace(
                        memory_item(),
                        id=job.memory_id,
                        source_event_ids=job.source_event_ids,
                        primary_source_event_id=job.source_event_ids[0],
                    )
                )
                await tx.graph_write_jobs.enqueue(job)

        worker = GraphWriteWorker(
            store,
            graph_backend=_MixedOutcomeGraphBackend(store),
            worker_id="graph_worker_001",
            retry_delay=timedelta(seconds=30),
            batch_size=8,
        )

        with pytest.raises(OutboxLockOwnershipError):
            await worker.run_once(now=NOW)

        job_by_id = {job.id: job for job in store.graph_write_jobs}
        assert job_by_id["graph_job_success"].status == "succeeded"
        assert job_by_id["graph_job_retry"].status == "pending"
        assert job_by_id["graph_job_retry"].attempts == 1
        assert job_by_id["graph_job_retry"].last_error == "ProviderTransientFailure"
        assert job_by_id["graph_job_dead"].status == "dead_letter"
        assert job_by_id["graph_job_dead"].dead_letter_reason == "ProviderPermanentFailure"
        assert job_by_id["graph_job_lock_lost"].status == "processing"
        assert job_by_id["graph_job_lock_lost"].locked_by == "graph_worker_002"
        assert [event.stage for event in store.audit_events].count(
            "graph_write.backend.started"
        ) == 4
        assert [
            event.stage
            for event in store.audit_events
            if event.stage != "graph_write.backend.started"
        ] == [
            "graph_write.succeeded",
            "graph_write.retry",
            "graph_write.dead_letter",
            "graph_write.lock_lost",
        ]
        assert any(
            link.memory_id == "memory_success" and link.backend_object_id == "episode_success"
            for link in store.memory_graph_links
        )
        assert all(link.memory_id != "memory_retry" for link in store.memory_graph_links)
        assert all(link.memory_id != "memory_dead" for link in store.memory_graph_links)
        assert all(link.memory_id != "memory_lock_lost" for link in store.memory_graph_links)

    asyncio.run(scenario())


class _MixedOutcomeGraphBackend:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def search_current(self, query):
        raise NotImplementedError

    async def search_history(self, query):
        raise NotImplementedError

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        raise NotImplementedError

    async def ingest_graph_jobs(self, request: GraphWriteBatchRequest) -> GraphWriteBatchResult:
        async with self._store.transaction() as tx:
            job = tx.state.graph_write_jobs["graph_job_lock_lost"]
            tx.state.graph_write_jobs[job.id] = replace(
                job,
                locked_by="graph_worker_002",
                lock_expires_at=NOW + timedelta(minutes=5),
            )

        return GraphWriteBatchResult(
            items=(
                GraphWriteBatchItemResult(
                    job_id="graph_job_success",
                    result=successful_graph_result_for("success"),
                    error_type=None,
                    error_message=None,
                    reason_code=None,
                    retryable=False,
                ),
                GraphWriteBatchItemResult(
                    job_id="graph_job_retry",
                    result=None,
                    error_type="ProviderTransientFailure",
                    error_message="Provider is temporarily unavailable.",
                    reason_code="provider_unavailable",
                    retryable=True,
                ),
                GraphWriteBatchItemResult(
                    job_id="graph_job_dead",
                    result=None,
                    error_type="ProviderPermanentFailure",
                    error_message="Provider returned invalid graph output.",
                    reason_code="provider_bad_output",
                    retryable=False,
                ),
                GraphWriteBatchItemResult(
                    job_id="graph_job_lock_lost",
                    result=successful_graph_result_for("lock_lost"),
                    error_type=None,
                    error_message=None,
                    reason_code=None,
                    retryable=False,
                ),
            )
        )

    async def mark_source_redacted(self, source_event_id, scope):
        raise NotImplementedError


def successful_graph_result_for(suffix: str) -> GraphWriteResult:
    result = successful_graph_result()
    return GraphWriteResult(
        backend=result.backend,
        facts=(),
        invalidated_facts=(),
        backend_episode_refs=(f"episode_{suffix}",),
        backend_fact_refs=(),
    )


def _derived_source_event(source_event_id: str) -> SourceEvent:
    return replace(
        source_event(),
        id=source_event_id,
        raw_payload_hash=f"hash_{source_event_id}",
        runtime_event_idempotency_key=f"runtime-key-{source_event_id}",
    )


def _derived_job(
    job_id: str,
    memory_id: str,
    source_event_id: str,
    *,
    max_attempts: int = 3,
    order: int = 0,
) -> GraphWriteJob:
    return replace(
        graph_job(max_attempts=max_attempts),
        id=job_id,
        memory_id=memory_id,
        source_event_ids=(source_event_id,),
        idempotency_key=f"graph:{memory_id}",
        created_at=NOW + timedelta(seconds=order),
    )
