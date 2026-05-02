from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from memwing.api.server import create_app
from memwing.core.memory_access import MemoryAccessSearchResult
from memwing.core.runtime import AgentContextResult, AgentRuntimeStatusResult, RememberEventResult
from memwing.ports.agent_runtime import AgentRuntimePort


class FakeRuntime(AgentRuntimePort):
    async def build_context(self, request):
        return AgentContextResult(
            messages=None,
            system_prompt_addition="MemWing context",
            context_blocks=(),
            estimated_tokens=2,
            trace_id="trace-context",
        )

    async def remember_runtime_event(self, event):
        return RememberEventResult(
            accepted=True,
            source_event_id="evt_001",
            trace_id="trace-ingest",
        )

    async def knowledge_search(self, query):
        return MemoryAccessSearchResult(
            contexts=(),
            results=(),
            next_cursor=None,
            trace_id="trace-search",
        )

    async def knowledge_get(self, request):
        raise AssertionError("not used")

    async def knowledge_explain(self, request):
        raise AssertionError("not used")

    async def runtime_status(self, request):
        return AgentRuntimeStatusResult(
            runtime_ref=request.runtime_ref,
            healthy=True,
            capabilities=("fastapi_http",),
            trace_id="trace-status",
        )


@asynccontextmanager
async def fake_runtime_context() -> AsyncIterator[AgentRuntimePort]:
    yield FakeRuntime()


def test_healthz_returns_process_health() -> None:
    app = create_app(runtime_context_factory=fake_runtime_context)

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_memwing_tool_route_delegates_to_openclaw_http_boundary() -> None:
    app = create_app(runtime_context_factory=fake_runtime_context)

    with TestClient(app) as client:
        response = client.post(
            "/v1/memwing/tools/search-memory",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "session_001",
                "query": "demo scope",
                "limit": 5,
                "scope": {"project_memory_space_id": "project_001"},
            },
        )

    assert response.status_code == 200
    assert response.json()["trace_id"] == "trace-search"


def test_openclaw_ingest_route_delegates_to_openclaw_http_boundary() -> None:
    app = create_app(runtime_context_factory=fake_runtime_context)

    with TestClient(app) as client:
        response = client.post(
            "/v1/openclaw/events/ingest",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "session_001",
                "run_id": "run_001",
                "message_id": "message_001",
                "hook_name": "ingest",
                "scope": {"project_memory_space_id": "project_001"},
                "content": "Event content",
                "payload": {"kind": "ingest"},
                "event_time": "2026-04-28T00:00:00+00:00",
            },
        )

    assert response.status_code == 202
    assert response.json()["accepted"] is True


def test_unknown_route_returns_error_envelope() -> None:
    app = create_app(runtime_context_factory=fake_runtime_context)

    with TestClient(app) as client:
        response = client.post("/v1/unknown", json={})

    assert response.status_code == 404
    assert response.json()["ok"] is False
    assert response.json()["code"] == "route_not_found"
