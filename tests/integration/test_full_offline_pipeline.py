from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from memwing.api.server import create_app


def test_full_offline_pipeline_requires_live_derived_backends() -> None:
    if os.environ.get("MEMWING_FULL_OFFLINE_PIPELINE_LIVE") != "true":
        pytest.skip(
            "set MEMWING_FULL_OFFLINE_PIPELINE_LIVE=true with Postgres, Qdrant, and Neo4j "
            "reachable to run the full offline pipeline smoke"
        )

    required = {
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "QDRANT_URL": os.environ.get("QDRANT_URL"),
        "MEMWING_GRAPHITI_NEO4J_URI": os.environ.get("MEMWING_GRAPHITI_NEO4J_URI"),
        "MEMWING_BENCHMARK_ADMIN_ENABLED": os.environ.get("MEMWING_BENCHMARK_ADMIN_ENABLED"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        pytest.skip(f"full offline pipeline live smoke missing env: {', '.join(missing)}")

    if os.environ.get("MEMWING_BENCHMARK_ADMIN_ENABLED") != "true":
        pytest.skip("set MEMWING_BENCHMARK_ADMIN_ENABLED=true for live pipeline smoke")

    app = create_app()
    scope = {
        "project_memory_space_id": "benchmark:live-smoke:case1",
        "group_id": "benchmark:live-smoke",
        "thread_id": "benchmark:live-smoke",
    }
    with TestClient(app) as client:
        cleanup = client.post(
            "/v1/memwing/admin/benchmark/cleanup-scope",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "benchmark:live-smoke",
                "scope": scope,
            },
        )
        ingest = client.post(
            "/v1/openclaw/events/ingest",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "benchmark:live-smoke",
                "run_id": "live-smoke",
                "message_id": "message_001",
                "hook_name": "ingest",
                "sequence": 1,
                "scope": scope,
                "content": "MemWing live smoke owner is Shen Nan.",
                "payload": {"kind": "live-smoke"},
                "event_time": "2026-05-02T00:00:00+00:00",
            },
        )
        drain = client.post("/v1/memwing/admin/benchmark/drain", json={"scope": scope})
        readiness = client.post(
            "/v1/memwing/admin/benchmark/readiness",
            json={
                "scope": scope,
                "expected_source_event_ids": [ingest.json().get("source_event_id")],
                "queries": ["Shen Nan"],
            },
        )
        search = client.post(
            "/v1/memwing/tools/search-memory",
            json={
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "benchmark:live-smoke",
                "scope": scope,
                "query": "Shen Nan",
                "mode": "current",
                "limit": 5,
            },
        )

    assert cleanup.status_code == 200
    assert ingest.status_code == 202
    assert drain.status_code == 200
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True
    assert search.status_code == 200
    assert any(
        result["source"] in {"evidence_index", "graph_backend"}
        for result in search.json()["results"]
    )
