import asyncio
from datetime import UTC, datetime

from memwing.api.openclaw_http import handle_openclaw_http_request
from memwing.application.access_service import MemoryAccessService
from memwing.application.gateway_service import MemoryGateway
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.scope import ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter
from memwing.infrastructure.db.in_memory import InMemoryDataStore


EVENT_TIME = datetime(2026, 4, 28, tzinfo=UTC)


def test_openclaw_plugin_ingest_url_writes_runtime_event_to_memory_gateway() -> None:
    async def run() -> None:
        store = _store()
        runtime = _runtime(store)

        response = await handle_openclaw_http_request(
            method="POST",
            path="/v1/openclaw/events/ingest",
            payload=_event_payload("ingest"),
            runtime=runtime,
        )

        assert response.status_code == 202
        assert response.body["accepted"] is True
        assert len(store.source_events) == 1
        assert len(store.audit_events) == 1
        assert len(store.outbox_jobs) == 4
        assert store.source_events[0].runtime_event_idempotency_key == (
            "openclaw:main:session_001:run_001:ingest:message_001"
        )

    asyncio.run(run())


def test_openclaw_plugin_tool_url_uses_memory_access_service() -> None:
    async def run() -> None:
        store = _store()
        runtime = _runtime(store)

        response = await handle_openclaw_http_request(
            method="POST",
            path="/v1/memwing/tools/search-memory",
            payload={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "session_001",
                "query": "demo scope",
                "limit": 5,
                "scope": {"project_memory_space_id": "project_001"},
            },
            runtime=runtime,
        )

        assert response.status_code == 200
        assert response.body["results"] == []
        assert response.body["contexts"] == []
        assert response.body["trace_id"].startswith("memory_access:search:")

    asyncio.run(run())


def test_openclaw_documented_tool_url_uses_same_memory_access_boundary() -> None:
    async def run() -> None:
        store = _store()
        runtime = _runtime(store)

        response = await handle_openclaw_http_request(
            method="POST",
            path="/v1/tools/memwing/search-memory",
            payload={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "session_001",
                "query": "demo scope",
                "limit": 5,
                "scope": {"project_memory_space_id": "project_001"},
            },
            runtime=runtime,
        )

        assert response.status_code == 200
        assert response.body["results"] == []
        assert response.body["trace_id"] == "memory_access:search:main"

    asyncio.run(run())


def test_openclaw_http_boundary_returns_schema_error_envelope() -> None:
    async def run() -> None:
        store = _store()
        runtime = _runtime(store)

        response = await handle_openclaw_http_request(
            method="POST",
            path="/v1/memwing/tools/search-memory",
            payload={
                "agent_id": "main",
                "query": "demo scope",
                "max_results": 5,
                "scope": {"project_memory_space_id": "project_001"},
            },
            runtime=runtime,
        )

        assert response.status_code == 400
        assert response.body["ok"] is False
        assert response.body["code"] == "schema_invalid"
        assert "max_results" in response.body["message"]

    asyncio.run(run())


def test_openclaw_http_boundary_returns_scope_error_envelope() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        store.add_project_memory_space(
            ProjectMemorySpace(
                id="project_001",
                name="Demo",
                default_safe_mode_enabled=False,
            )
        )
        runtime = _runtime(store)

        response = await handle_openclaw_http_request(
            method="POST",
            path="/v1/openclaw/events/ingest",
            payload=_event_payload("ingest"),
            runtime=runtime,
        )

        assert response.status_code == 403
        assert response.body["ok"] is False
        assert response.body["code"] == "scope_resolution_failed"
        assert "runtime scope binding" in response.body["message"]
        assert store.source_events == ()
        assert len(store.audit_events) == 1
        assert store.audit_events[0].stage == "remember_event.rejected"
        assert store.audit_events[0].reason_code == "scope_resolution_failed"

    asyncio.run(run())


def test_openclaw_tool_boundary_returns_scope_error_envelope() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        store.add_project_memory_space(
            ProjectMemorySpace(
                id="project_001",
                name="Demo",
                default_safe_mode_enabled=False,
            )
        )
        runtime = _runtime(store)

        response = await handle_openclaw_http_request(
            method="POST",
            path="/v1/memwing/tools/search-memory",
            payload={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "session_001",
                "query": "demo scope",
                "scope": {"project_memory_space_id": "project_001"},
            },
            runtime=runtime,
        )

        assert response.status_code == 403
        assert response.body["ok"] is False
        assert response.body["code"] == "scope_resolution_failed"
        assert "runtime scope binding" in response.body["message"]

    asyncio.run(run())


def _runtime(store: InMemoryDataStore) -> OpenClawAdapter:
    resolver = ScopeResolver(store)
    return OpenClawAdapter(MemoryGateway(store, resolver), MemoryAccessService(resolver))


def _store() -> InMemoryDataStore:
    store = InMemoryDataStore()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Demo",
            default_safe_mode_enabled=False,
        )
    )
    store.add_runtime_scope_binding(
        RuntimeScopeBinding(
            runtime="openclaw",
            agent_id="main",
            workspace_id="workspace_001",
            session_key_pattern="session_001",
            project_memory_space_id="project_001",
        )
    )
    return store


def _event_payload(hook_name: str) -> dict[str, object]:
    return {
        "agent_id": "main",
        "workspace_id": "workspace_001",
        "session_id": "session_001",
        "run_id": "run_001",
        "message_id": "message_001",
        "hook_name": hook_name,
        "sequence": 1,
        "scope": {"project_memory_space_id": "project_001"},
        "content": "Event content",
        "payload": {"kind": hook_name},
        "event_time": EVENT_TIME,
    }
