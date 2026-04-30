import asyncio
from dataclasses import replace
from datetime import timedelta
import uuid

import pytest

from memwing.api.agent_runtime import AgentMemoryQuery, AgentMemorySearchResult
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import AuditEvent, GraphFact, GraphWriteResult, MemoryGraphLink, MemoryStatus
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.db.in_memory_graph_repositories import (
    InMemoryMemoryGraphLinkRepository,
)
from memwing.ports.graph_backend import GraphWriteRequest
from memwing.ports.lifecycle_transition import LifecycleTransitionRequest, LifecycleTransitionResult
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
        assert store.audit_events[-1].reason_text == "TimeoutError"

    asyncio.run(scenario())


def test_graph_write_worker_marks_invalidated_fact_memories_needs_review() -> None:
    store = InMemoryDataStore()
    invalidated_source = replace(source_event(), id="source_old", content="Old decision.")
    invalidated_memory = replace(
        memory_item(),
        id="memory_old",
        source_event_ids=("source_old",),
        primary_source_event_id="source_old",
        status=MemoryStatus.ACTIVE,
    )
    graph_result = replace(
        successful_graph_result(),
        invalidated_facts=(
            GraphFact(
                backend="graphiti",
                fact_id="fact_old",
                fact_text="Old decision.",
                source_event_ids=("source_old",),
                valid_from=None,
                valid_to=NOW,
                invalidated_at=NOW,
                confidence=0.8,
                metadata={},
            ),
        ),
    )

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(source_event())
            await tx.source_events.insert_if_absent(invalidated_source)
            await tx.memory_items.upsert(memory_item())
            await tx.memory_items.upsert(invalidated_memory)
            await tx.graph_write_jobs.enqueue(graph_job())

        lifecycle = FakeLifecycleTransition(store)
        worker = GraphWriteWorker(
            store,
            graph_backend=FakeGraphBackend(graph_result),
            lifecycle_transition=lifecycle,
            worker_id="graph_worker_001",
        )

        result = await worker.run_once(now=NOW)

        async with store.transaction() as tx:
            updated = await tx.memory_items.get("memory_old")

        assert result.succeeded == 1
        assert updated is not None
        assert updated.status is MemoryStatus.NEEDS_REVIEW
        assert lifecycle.requests == (
            LifecycleTransitionRequest(
                memory_id="memory_old",
                action=LifecycleAction.MARK_NEEDS_REVIEW,
                actor_id="graph_write_worker",
                reason="graph fact invalidated",
                idempotency_key="graph:graph_job_001:invalidated:memory_old",
                trace_id="graph_write:graph_job_001",
                now=NOW,
            ),
        )
        assert store.audit_events[-1].stage == "graph_write.succeeded"

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


class HangingGraphBackend:
    async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        raise NotImplementedError

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        await asyncio.Event().wait()

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError


class FakeLifecycleTransition:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store
        self.requests: tuple[LifecycleTransitionRequest, ...] = ()

    async def transition(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransitionResult:
        self.requests = (*self.requests, request)
        async with self._store.transaction() as tx:
            memory = await tx.memory_items.get(request.memory_id)
            assert memory is not None
            updated = replace(
                memory,
                status=MemoryStatus.NEEDS_REVIEW,
                updated_at=request.now,
            )
            await tx.memory_items.upsert(updated)

        audit_event = AuditEvent(
            id=str(uuid.uuid4()),
            trace_id=request.trace_id,
            entity_type="memory_item",
            entity_id=request.memory_id,
            stage="memory.lifecycle_transition",
            input_ref=request.memory_id,
            output_ref=updated.status,
            decision=request.action.value,
            reason_code=None,
            reason_text=request.reason,
            source_event_ids=updated.source_event_ids,
            latency_ms=None,
            created_at=request.now,
            actor_id=request.actor_id,
        )
        return LifecycleTransitionResult(
            memory_item=updated,
            previous_status=memory.status,
            audit_event=audit_event,
        )
