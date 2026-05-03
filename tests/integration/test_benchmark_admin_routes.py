from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from memwing.api.server import create_app
from memwing.application.access_service import MemoryAccessService
from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.application.long_term_filter_service import LongTermFilterService
from memwing.application.scope_resolver import ScopeResolver
from memwing.bootstrap import MemWingApiRuntimeContext
from memwing.core.memory_search import MemorySearchResult, MemorySearchResultItem
from memwing.core.models import LongTermFilterItem, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter
from memwing.application.gateway_service import MemoryGateway
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.db.in_memory_benchmark_admin import InMemoryBenchmarkAdminStore
from memwing.ports.llm_filter import LongTermFilterRequest
from memwing.workers.benchmark_drain import BenchmarkDrainWorker


def test_benchmark_admin_routes_are_hidden_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("MEMWING_BENCHMARK_ADMIN_ENABLED", raising=False)
    app = create_app(runtime_context_factory=_runtime_context_factory())

    with TestClient(app) as client:
        response = client.post("/v1/memwing/admin/benchmark/readiness", json={})

    assert response.status_code == 404


def test_benchmark_admin_cleanup_ingest_drain_readiness_route(monkeypatch) -> None:
    monkeypatch.setenv("MEMWING_BENCHMARK_ADMIN_ENABLED", "true")
    store = InMemoryDataStore()
    evidence = _EvidenceIndex()
    app = create_app(runtime_context_factory=_runtime_context_factory(store, evidence))
    scope = {
        "project_memory_space_id": "benchmark:run1:case1",
        "group_id": "benchmark:case1",
        "thread_id": "benchmark:case1",
    }

    with TestClient(app) as client:
        cleanup = client.post(
            "/v1/memwing/admin/benchmark/cleanup-scope",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "benchmark:case1",
                "scope": scope,
            },
        )
        ingest = client.post(
            "/v1/openclaw/events/ingest",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "benchmark:case1",
                "run_id": "run1",
                "message_id": "message_001",
                "hook_name": "ingest",
                "sequence": 1,
                "scope": scope,
                "content": "云帆看板负责人是沈南。",
                "payload": {"kind": "seed"},
                "event_time": "2026-05-02T00:00:00+00:00",
            },
        )
        drain = client.post(
            "/v1/memwing/admin/benchmark/drain",
            json={"scope": scope, "max_rounds": 3},
        )
        legacy_drain = client.post(
            "/v1/memwing/admin/benchmark/drain",
            json={"scope": scope, "max_iterations": 3},
        )
        source_event_id = ingest.json()["source_event_id"]
        readiness = client.post(
            "/v1/memwing/admin/benchmark/readiness",
            json={
                "scope": scope,
                "expected_source_event_ids": [source_event_id],
                "queries": ["沈南"],
            },
        )
        search = client.post(
            "/v1/memwing/tools/search-memory",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "benchmark:case1",
                "scope": scope,
                "query": "沈南",
                "mode": "current",
                "limit": 5,
            },
        )

    assert cleanup.status_code == 200
    assert cleanup.json()["deleted"]["source_events"] == 0
    assert cleanup.json()["trace_id"].startswith("benchmark_cleanup:")
    assert ingest.status_code == 202
    assert drain.status_code == 200
    assert drain.json()["outbox"]["succeeded"] == 4
    assert drain.json()["evidence_indexed"]["source_events"] == 1
    assert drain.json()["pending"] == {"outbox_jobs": 0, "graph_write_jobs": 0}
    assert drain.json()["trace_id"].startswith("benchmark_drain:")
    assert legacy_drain.status_code == 400
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True
    assert readiness.json()["postgres"]["source_events"] == 1
    assert readiness.json()["evidence"]["ready"] is True
    assert readiness.json()["evidence"]["matched_source_event_ids"] == [source_event_id]
    assert readiness.json()["page_memory"]["ready"] is False
    assert readiness.json()["memory_items"]["count"] == 0
    assert readiness.json()["trace_id"].startswith("benchmark_readiness:")
    assert readiness.json()["queries"][0]["source_mix"] == {"evidence_index": 1}
    assert readiness.json()["queries"][0]["evidence"]["ready"] is True
    assert search.status_code == 200
    assert search.json()["results"][0]["source"] == "evidence_index"


def _runtime_context_factory(
    store: InMemoryDataStore | None = None,
    evidence: object | None = None,
):
    @asynccontextmanager
    async def context() -> AsyncIterator[MemWingApiRuntimeContext]:
        data_store = store or InMemoryDataStore()
        evidence_index = evidence or _EvidenceIndex()
        resolver = ScopeResolver(data_store)
        runtime = OpenClawAdapter(
            MemoryGateway(data_store, resolver),
            MemoryAccessService(resolver, data_store, evidence_index=evidence_index),
        )
        admin = BenchmarkAdminService(
            unit_of_work=data_store,
            admin_store=InMemoryBenchmarkAdminStore(data_store),
            drain_worker=BenchmarkDrainWorker(
                data_store,
                evidence_index=evidence_index,
                long_term_filter=LongTermFilterService(data_store, _NoopLongTermFilter()),
                page_memory_worker=None,
                graph_write_worker=None,
            ),
            graph_backend=None,
            evidence_index=evidence_index,
        )
        yield MemWingApiRuntimeContext(runtime=runtime, benchmark_admin=admin)

    return context


class _EvidenceIndex:
    def __init__(self) -> None:
        self._events: list[SourceEvent] = []

    async def index_source_event(self, source_event: SourceEvent, scope: EffectiveScope) -> None:
        self._events.append(source_event)

    async def search(self, query) -> MemorySearchResult:
        results = tuple(
            MemorySearchResultItem(
                id=f"evidence:{event.id}",
                text=event.content,
                score=1.0,
                source="evidence_index",
                source_event_ids=(event.id,),
                memory_item_ids=(),
                valid_from=event.event_time,
                valid_to=None,
                metadata={},
            )
            for event in self._events
            if query.query in event.content
            and event.project_memory_space_id == query.scope.project_memory_space_id
        )
        return MemorySearchResult(
            contexts=tuple(item.text for item in results),
            results=results,
            next_cursor=None,
            trace_id=query.trace_id or "trace",
        )


class _NoopLongTermFilter:
    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        return ()
