import asyncio
from datetime import timedelta

import pytest

from memwing.core.errors import ProviderPermanentFailure, ProviderTransientFailure
from memwing.core.models import MemoryGraphLink
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.db.in_memory_graph_repositories import (
    InMemoryMemoryGraphLinkRepository,
)
from memwing.workers.graph_write_worker import GraphWriteWorker
from tests.integration.graph_write_worker_fixtures import (
    FailingGraphBackend,
    FakeGraphBackend,
    HangingGraphBackend,
    NOW,
    graph_job,
    graph_result_with_invalidated_fact,
    invalidated_memory_item,
    invalidated_source_event,
    memory_item,
    source_event,
    successful_graph_result,
)


def test_graph_write_worker_retries_then_dead_letters_backend_failures() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job(max_attempts=2))

        worker = GraphWriteWorker(
            store,
            graph_backend=TransientFailureGraphBackend(),
            worker_id="graph_worker_001",
            retry_delay=timedelta(seconds=30),
        )

        first = await worker.run_once(now=NOW)
        retry_job = store.graph_write_jobs[0]
        second = await worker.run_once(now=NOW + timedelta(seconds=30))

        assert first.retried == 1
        assert retry_job.status == "pending"
        assert retry_job.attempts == 1
        assert retry_job.last_error == "ProviderTransientFailure"
        assert retry_job.next_run_at == NOW + timedelta(seconds=30)
        assert second.dead_lettered == 1
        assert store.graph_write_jobs[0].status == "dead_letter"
        assert store.graph_write_jobs[0].attempts == 2
        assert store.graph_write_jobs[0].dead_letter_reason == "ProviderTransientFailure"
        assert store.memory_graph_links == ()
        assert [event.stage for event in store.audit_events] == [
            "graph_write.retry",
            "graph_write.dead_letter",
        ]
        assert [event.reason_code for event in store.audit_events] == [
            "provider_unavailable",
            "provider_unavailable",
        ]
        assert [event.reason_text for event in store.audit_events] == [
            "ProviderTransientFailure",
            "ProviderTransientFailure",
        ]

    asyncio.run(scenario())


def test_graph_write_worker_retries_backend_timeout_without_hanging() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job())

        worker = GraphWriteWorker(
            store,
            graph_backend=HangingGraphBackend(),
            worker_id="graph_worker_001",
            retry_delay=timedelta(seconds=30),
            backend_timeout=timedelta(milliseconds=1),
        )

        result = await asyncio.wait_for(worker.run_once(now=NOW), timeout=1)
        retry_job = store.graph_write_jobs[0]

        assert result.claimed == 1
        assert result.retried == 1
        assert retry_job.status == "pending"
        assert retry_job.attempts == 1
        assert retry_job.last_error == "TimeoutError"
        assert retry_job.next_run_at == NOW + timedelta(seconds=30)
        assert store.audit_events[-1].stage == "graph_write.retry"
        assert store.audit_events[-1].reason_code == "provider_timeout"
        assert store.audit_events[-1].reason_text == "TimeoutError"

    asyncio.run(scenario())


def test_graph_write_worker_dead_letters_permanent_provider_failure_without_retry() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job(max_attempts=3))

        worker = GraphWriteWorker(
            store,
            graph_backend=PermanentFailureGraphBackend(),
            worker_id="graph_worker_001",
            retry_delay=timedelta(seconds=30),
        )

        result = await worker.run_once(now=NOW)
        job = store.graph_write_jobs[0]

        assert result.retried == 0
        assert result.dead_lettered == 1
        assert job.status == "dead_letter"
        assert job.attempts == 1
        assert job.last_error == "ProviderPermanentFailure"
        assert job.dead_letter_reason == "ProviderPermanentFailure"
        assert job.next_run_at == NOW
        assert store.audit_events[-1].stage == "graph_write.dead_letter"
        assert store.audit_events[-1].reason_code == "provider_bad_output"
        assert store.audit_events[-1].reason_text == "ProviderPermanentFailure"

    asyncio.run(scenario())


def test_graph_write_worker_dead_letter_error_summary_excludes_raw_content() -> None:
    store = InMemoryDataStore()
    raw_values = (
        source_event().content,
        memory_item().content,
        successful_graph_result().facts[0].fact_text,
    )
    raw_exception_text = "backend failed while handling " + " | ".join(raw_values)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job(max_attempts=1))

        worker = GraphWriteWorker(
            store,
            graph_backend=FailingGraphBackend(raw_exception_text),
            worker_id="graph_worker_001",
        )

        result = await worker.run_once(now=NOW)

        audit_reason = store.audit_events[-1].reason_text or ""
        job = store.graph_write_jobs[0]

        assert result.dead_lettered == 1
        assert job.last_error == "RuntimeError"
        assert job.dead_letter_reason == "RuntimeError"
        assert audit_reason == "RuntimeError"
        for raw_value in raw_values:
            assert raw_value not in audit_reason
            assert raw_value not in (job.last_error or "")
            assert raw_value not in (job.dead_letter_reason or "")

    asyncio.run(scenario())


class PermanentFailureGraphBackend:
    async def search_current(self, query):
        raise NotImplementedError

    async def search_history(self, query):
        raise NotImplementedError

    async def ingest_graph_job(self, request):
        raise ProviderPermanentFailure(
            "provider_bad_output",
            "Provider returned invalid graph output.",
        )

    async def mark_source_redacted(self, source_event_id, scope):
        raise NotImplementedError


class TransientFailureGraphBackend:
    async def search_current(self, query):
        raise NotImplementedError

    async def search_history(self, query):
        raise NotImplementedError

    async def ingest_graph_job(self, request):
        raise ProviderTransientFailure(
            "provider_unavailable",
            "Provider is temporarily unavailable.",
        )

    async def mark_source_redacted(self, source_event_id, scope):
        raise NotImplementedError


def test_graph_write_worker_dead_letters_missing_memory_without_backend_call() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.graph_write_jobs.enqueue(graph_job(max_attempts=1))

        backend = FakeGraphBackend(successful_graph_result())
        worker = GraphWriteWorker(
            store,
            graph_backend=backend,
            worker_id="graph_worker_001",
        )

        result = await worker.run_once(now=NOW)

        assert result.dead_lettered == 1
        assert backend.requests == ()
        assert store.graph_write_jobs[0].status == "dead_letter"
        assert store.graph_write_jobs[0].dead_letter_reason == "missing memory item memory_001"
        assert store.memory_graph_links == ()
        assert store.audit_events[-1].stage == "graph_write.dead_letter"
        assert "Decision source text." not in (store.audit_events[-1].reason_text or "")

    asyncio.run(scenario())


def test_graph_write_worker_dead_letters_missing_source_event_without_backend_call() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job(max_attempts=1))

        backend = FakeGraphBackend(successful_graph_result())
        worker = GraphWriteWorker(
            store,
            graph_backend=backend,
            worker_id="graph_worker_001",
        )

        result = await worker.run_once(now=NOW)

        assert result.dead_lettered == 1
        assert backend.requests == ()
        assert store.graph_write_jobs[0].status == "dead_letter"
        assert store.graph_write_jobs[0].dead_letter_reason == "missing source event source_001"
        assert store.memory_graph_links == ()
        assert store.audit_events[-1].stage == "graph_write.dead_letter"

    asyncio.run(scenario())


def test_graph_write_worker_dead_letters_link_write_failure_without_partial_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_values = (
        source_event().content,
        memory_item().content,
        successful_graph_result().facts[0].fact_text,
    )

    async def fail_upsert(
        self: InMemoryMemoryGraphLinkRepository,
        link: MemoryGraphLink,
    ) -> MemoryGraphLink:
        raise RuntimeError("link write failed for " + " | ".join(raw_values))

    monkeypatch.setattr(InMemoryMemoryGraphLinkRepository, "upsert", fail_upsert)
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
            retry_delay=timedelta(seconds=30),
        )

        result = await worker.run_once(now=NOW)

        assert result.dead_lettered == 1
        assert store.graph_write_jobs[0].status == "dead_letter"
        assert store.graph_write_jobs[0].last_error == "RuntimeError"
        assert store.graph_write_jobs[0].dead_letter_reason == "RuntimeError"
        assert store.memory_graph_links == ()
        assert store.audit_events[-1].stage == "graph_write.dead_letter"
        assert store.audit_events[-1].reason_code == "unexpected_failure"
        assert store.audit_events[-1].reason_text == "RuntimeError"
        for raw_value in raw_values:
            assert raw_value not in (store.audit_events[-1].reason_text or "")
            assert raw_value not in (store.graph_write_jobs[0].last_error or "")
            assert raw_value not in (store.graph_write_jobs[0].dead_letter_reason or "")

    asyncio.run(scenario())


def test_graph_write_worker_dead_letters_missing_lifecycle_port_without_partial_links() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.source_events.insert_if_absent(invalidated_source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.memory_items.upsert(invalidated_memory_item())
            await tx.graph_write_jobs.enqueue(graph_job(max_attempts=1))

        backend = FakeGraphBackend(graph_result_with_invalidated_fact())
        worker = GraphWriteWorker(
            store,
            graph_backend=backend,
            worker_id="graph_worker_001",
        )

        result = await worker.run_once(now=NOW)

        assert result.dead_lettered == 1
        assert backend.requests
        assert store.graph_write_jobs[0].status == "dead_letter"
        assert (
            store.graph_write_jobs[0].dead_letter_reason
            == "lifecycle transition port required for graph invalidations"
        )
        assert store.memory_graph_links == ()
        assert store.audit_events[-1].stage == "graph_write.dead_letter"

    asyncio.run(scenario())
