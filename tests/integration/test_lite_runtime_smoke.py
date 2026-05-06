from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from memwing.api.server import create_app


def test_lite_runtime_ingests_searches_sources_and_exposes_control_reads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEMWING_PROFILE", "lite")
    monkeypatch.setenv("MEMWING_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("MEMWING_LITE_DB_PATH", str(tmp_path / "memwing.db"))
    monkeypatch.setenv("MEMWING_DEFAULT_PROJECT_MEMORY_SPACE_ID", "project_001")
    monkeypatch.setenv("MEMWING_OPENCLAW_WORKSPACE_ID", "workspace_001")

    app = create_app()
    with TestClient(app) as client:
        ingest_response = client.post("/v1/openclaw/events/ingest", json=_event_payload())
        manual_response = client.post(
            "/v1/control/memories/manual",
            params={"project_memory_space_id": "project_001"},
            json={
                "actor_id": "operator",
                "reason": "lite smoke",
                "idempotency_key": "manual-lite-memory",
                "title": "Lite runtime memory",
                "content": "Lite memory foundation searchable fact.",
            },
        )
        memory_search_response = client.post(
            "/v1/memwing/tools/search-memory",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "session_001",
                "query": "searchable fact",
                "limit": 5,
                "scope": {"project_memory_space_id": "project_001"},
            },
        )
        control_sources_response = client.get(
            "/v1/control/source-events",
            params={"project_memory_space_id": "project_001", "limit": "10"},
        )

    assert ingest_response.status_code == 202
    assert manual_response.status_code == 202
    assert memory_search_response.status_code == 200
    assert "Lite memory foundation searchable fact." in memory_search_response.json()["results"][0]["text"]
    assert control_sources_response.status_code == 200
    source_id = control_sources_response.json()["items"][0]["id"]
    assert source_id

    with TestClient(app) as client:
        readiness_response = client.post(
            "/v1/memwing/pipeline/readiness",
            json={
                "source_event_ids": [source_id],
                "profile": "minimal-ingest",
                "scope": {"project_memory_space_id": "project_001"},
            },
        )
    assert readiness_response.status_code == 200
    body = readiness_response.json()
    assert body["derived"]["evidence"]["reason"] == "evidence_disabled"
    assert body["derived"]["graph"]["reason"] == "graph_disabled"


def _event_payload() -> dict[str, object]:
    return {
        "agent_id": "main",
        "workspace_id": "workspace_001",
        "session_id": "session_001",
        "run_id": "run_001",
        "message_id": "message_001",
        "hook_name": "ingest",
        "sequence": 1,
        "scope": {"project_memory_space_id": "project_001"},
        "content": "Lite memory foundation event",
        "payload": {"kind": "lite"},
        "event_time": datetime(2026, 5, 6, tzinfo=UTC).isoformat(),
    }
