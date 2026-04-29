import asyncio
from datetime import timedelta

import pytest

from memwing.api.agent_runtime import AgentMemoryQuery, AgentMemorySearchResult
from memwing.core.models import GraphWriteResult, MemoryGraphLink
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.db.in_memory_graph_repositories import (
    InMemoryMemoryGraphLinkRepository,
)
from memwing.ports.graph_backend import GraphWriteRequest
from memwing.workers.graph_write_worker import GraphWriteWorker
from tests.integration.graph_write_worker_fixtures import (
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


def test_graph_write_worker_retries_then_dead_letters_backend_failures() -> None:
    store = InMemoryDataStore()

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.memory_items.upsert(memory_item())
            await tx.graph_write_jobs.enqueue(graph_job(max_attempts=2))

        worker = GraphWriteWorker(
            store,
            graph_backend=FailingGraphBackend("backend unavailable"),
            worker_id="graph_worker_001",
            retry_delay=timedelta(seconds=30),
        )

        first = await worker.run_once(now=NOW)
        retry_job = store.graph_write_jobs[0]
        second = await worker.run_once(now=NOW + timedelta(seconds=30))

        assert first.retried == 1
        assert retry_job.status == "pending"
        assert retry_job.attempts == 1
        assert retry_job.last_error == "RuntimeError"
        assert retry_job.next_run_at == NOW + timedelta(seconds=30)
        assert second.dead_lettered == 1
        assert store.graph_write_jobs[0].status == "dead_letter"
        assert store.graph_write_jobs[0].attempts == 2
        assert store.graph_write_jobs[0].dead_letter_reason == "RuntimeError"
        assert store.memory_graph_links == ()
        assert [event.stage for event in store.audit_events] == [
            "graph_write.retry",
            "graph_write.dead_letter",
        ]
        assert [event.reason_text for event in store.audit_events] == [
            "RuntimeError",
            "RuntimeError",
        ]

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


def test_graph_write_worker_retries_link_write_failure_without_partial_links(
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

        assert result.retried == 1
        assert store.graph_write_jobs[0].status == "pending"
        assert store.graph_write_jobs[0].last_error == "RuntimeError"
        assert store.memory_graph_links == ()
        assert store.audit_events[-1].stage == "graph_write.retry"
        assert store.audit_events[-1].reason_text == "RuntimeError"
        for raw_value in raw_values:
            assert raw_value not in (store.audit_events[-1].reason_text or "")
            assert raw_value not in (store.graph_write_jobs[0].last_error or "")

    asyncio.run(scenario())


class FakeGraphBackend:
    def __init__(self, result: GraphWriteResult) -> None:
        self._result = result
        self.requests: tuple[GraphWriteRequest, ...] = ()

    async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        self.requests = (*self.requests, request)
        return self._result

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class FailingGraphBackend:
    def __init__(self, error: str) -> None:
        self._error = error

    async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        raise RuntimeError(self._error)

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError
