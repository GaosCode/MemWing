from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from memwing.api.server import create_app
from memwing.application.pipeline_readiness_service import PipelineReadinessService
from memwing.bootstrap import MemWingApiRuntimeContext
from memwing.core.memory_access import MemoryAccessSearchResult
from memwing.core.models import SourceEvent
from memwing.core.runtime import AgentContextResult, AgentRuntimeStatusResult, RememberEventResult
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.agent_runtime import AgentRuntimePort


NOW = datetime(2026, 5, 3, tzinfo=UTC)


def test_pipeline_readiness_route_returns_layered_status() -> None:
    store = InMemoryDataStore()
    _seed_source_event(store)
    app = create_app(runtime_context_factory=_context(store))

    with TestClient(app) as client:
        response = client.post(
            "/v1/memwing/pipeline/readiness",
            json={
                "source_event_ids": ["source_001"],
                "profile": "minimal-ingest",
                "scope": {
                    "project_memory_space_id": "project_001",
                    "group_id": "group_001",
                    "thread_id": "thread_001",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["source_events"]["available"] == 1
    assert body["outbox"]["pending"] == 0


def test_pipeline_await_timeout_returns_200_with_timed_out_body() -> None:
    store = InMemoryDataStore()
    app = create_app(runtime_context_factory=_context(store))

    with TestClient(app) as client:
        response = client.post(
            "/v1/memwing/pipeline/await",
            json={
                "source_event_ids": ["missing_source"],
                "profile": "minimal-ingest",
                "timeout_seconds": 0,
                "scope": {"project_memory_space_id": "project_001"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["timed_out"] is True


def _context(store: InMemoryDataStore):
    @asynccontextmanager
    async def factory() -> AsyncIterator[MemWingApiRuntimeContext]:
        yield MemWingApiRuntimeContext(
            runtime=_FakeRuntime(),
            pipeline_readiness=PipelineReadinessService(
                store,
                evidence_enabled=False,
                graph_enabled=False,
                poll_interval_seconds=0,
            ),
        )

    return factory


def _seed_source_event(store: InMemoryDataStore) -> None:
    async def seed() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(
                SourceEvent(
                    id="source_001",
                    project_memory_space_id="project_001",
                    group_id="group_001",
                    thread_id="thread_001",
                    shared_group_id=None,
                    author_id=None,
                    author_name=None,
                    source_type="text",
                    content="Content",
                    content_preview="Content",
                    source_url=None,
                    event_time=NOW,
                    raw_payload_hash="hash_source_001",
                    metadata={},
                    purged_at=None,
                    purged_by=None,
                    purge_reason=None,
                    purge_level="none",
                    graph_backend_raw_retained=False,
                    created_at=NOW,
                )
            )

    import asyncio

    asyncio.run(seed())


class _FakeRuntime(AgentRuntimePort):
    async def build_context(self, request):
        return AgentContextResult(
            messages=None,
            system_prompt_addition="",
            context_blocks=(),
            estimated_tokens=0,
            trace_id="trace-context",
        )

    async def remember_runtime_event(self, event):
        return RememberEventResult(accepted=True, source_event_id="source_001", trace_id="trace")

    async def knowledge_search(self, query):
        return MemoryAccessSearchResult(contexts=(), results=(), next_cursor=None, trace_id="trace")

    async def knowledge_get(self, request):
        raise AssertionError("not used")

    async def knowledge_explain(self, request):
        raise AssertionError("not used")

    async def runtime_status(self, request):
        return AgentRuntimeStatusResult(
            runtime_ref=request.runtime_ref,
            healthy=True,
            capabilities=(),
            trace_id="trace-status",
        )
