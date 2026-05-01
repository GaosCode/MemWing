from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import os
from pathlib import Path
import sys

import pytest

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_memory import AgentMemoryQuery
from memwing.core.models import (
    GraphWriteJob,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    SourceEvent,
)
from memwing.core.scope import MemoryScope
from memwing.infrastructure.graph.graphiti_adapter import (
    GraphitiAdapter,
    GraphitiConnectionConfig,
)
from memwing.infrastructure.graph.graphiti_embedder import GraphitiMemWingEmbedder
from memwing.infrastructure.graph.graphiti_llm import GraphitiMemWingLLMClient
from memwing.infrastructure.graph.graphiti_reranker import GraphitiNoProviderReranker
from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawRuntimeConfig,
    OpenClawRuntimeEmbeddingClient,
    OpenClawRuntimeLLMClient,
)
from memwing.ports.graph_backend import GraphWriteRequest
from memwing.ports.model_runtime import MemWingModelRole


NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.mark.skipif(
    os.environ.get("MEMWING_LIVE_GRAPHITI_KUZU") != "1",
    reason="set MEMWING_LIVE_GRAPHITI_KUZU=1 to run Graphiti Kuzu live smoke",
)
def test_graphiti_kuzu_live_uses_openclaw_llm_and_embedding(tmp_path: Path) -> None:
    graphiti = _kuzu_graphiti(tmp_path / "graphiti-live.kuzu")
    adapter = GraphitiAdapter(graphiti)

    try:
        result, search = asyncio.run(_run_graphiti_live(adapter))
    finally:
        asyncio.run(graphiti.close())

    assert result.facts
    assert result.backend_episode_refs
    assert search.contexts
    assert any("Skyline" in context for context in search.contexts)


@pytest.mark.skipif(
    os.environ.get("MEMWING_LIVE_GRAPHITI_NEO4J") != "1",
    reason="set MEMWING_LIVE_GRAPHITI_NEO4J=1 to run Graphiti Neo4j live smoke",
)
def test_graphiti_neo4j_live_uses_openclaw_llm_and_embedding() -> None:
    adapter = GraphitiAdapter.from_clients(
        GraphitiConnectionConfig(
            uri=os.environ.get("MEMWING_GRAPHITI_NEO4J_URI", "bolt://localhost:7687"),
            user=os.environ.get("MEMWING_GRAPHITI_NEO4J_USER", "neo4j"),
            password=_required_env("MEMWING_GRAPHITI_NEO4J_PASSWORD"),
        ),
        llm_client=_graphiti_llm_client(),
        embedder=_graphiti_embedder(),
        cross_encoder=GraphitiNoProviderReranker(),
    )

    result, search = asyncio.run(_run_graphiti_live(adapter))

    assert result.facts
    assert result.backend_episode_refs
    assert search.contexts
    assert any("Skyline" in context for context in search.contexts)


async def _run_graphiti_live(adapter: GraphitiAdapter):
    result = await adapter.ingest_graph_job(
        GraphWriteRequest(
            job=_graph_job(),
            memory_item=_memory_item(),
            source_events=(_source_event(),),
        )
    )
    search = await adapter.search_current(
        AgentMemoryQuery(
            runtime_ref=AgentRuntimeRef(runtime="openclaw", agent_id="agent_live_001"),
            query="Skyline codename owner",
            scope=MemoryScope(project_memory_space_id="project_graphiti_live_001"),
            limit=5,
        )
    )
    return result, search


def _kuzu_graphiti(db_path: Path):
    _install_graphiti_import_path()
    from graphiti_core import Graphiti
    from graphiti_core.driver.kuzu_driver import KuzuDriver

    return Graphiti(
        graph_driver=KuzuDriver(str(db_path)),
        llm_client=_graphiti_llm_client(),
        embedder=_graphiti_embedder(),
        cross_encoder=GraphitiNoProviderReranker(),
        store_raw_episode_content=True,
    )


def _install_graphiti_import_path() -> None:
    vendored_parent = Path(__file__).resolve().parents[2] / "memwing" / "infrastructure" / "graph"
    if str(vendored_parent) not in sys.path:
        sys.path.insert(0, str(vendored_parent))


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be set for Graphiti Neo4j live smoke")
    return value


def _graphiti_llm_client() -> GraphitiMemWingLLMClient:
    return GraphitiMemWingLLMClient(_openclaw_llm_for("graphiti_extraction"))


def _graphiti_embedder() -> GraphitiMemWingEmbedder:
    resolver = MemWingModelConfigResolver.from_env()
    selection = resolver.selection_for("graphiti_embedding")
    return GraphitiMemWingEmbedder(
        OpenClawRuntimeEmbeddingClient(OpenClawRuntimeConfig.from_env_model_selection(selection))
    )


def _openclaw_llm_for(role: MemWingModelRole) -> OpenClawRuntimeLLMClient:
    resolver = MemWingModelConfigResolver.from_env()
    selection = resolver.selection_for(role)
    return OpenClawRuntimeLLMClient(OpenClawRuntimeConfig.from_env_model_selection(selection))


def _source_event() -> SourceEvent:
    return SourceEvent(
        id="source_graphiti_live_001",
        project_memory_space_id="project_graphiti_live_001",
        group_id="group_graphiti_live_001",
        thread_id="thread_graphiti_live_001",
        shared_group_id=None,
        author_id="user_graphiti_live_001",
        author_name="Alice",
        source_type="text",
        content="Alice owns the Skyline codename decision for the MemWing Graphiti live test.",
        content_preview="Alice owns the Skyline codename decision.",
        source_url=None,
        event_time=NOW,
        raw_payload_hash="hash_graphiti_live_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=True,
        created_at=NOW,
        runtime_event_idempotency_key="runtime-graphiti-live-001",
    )


def _memory_item() -> MemoryItem:
    return MemoryItem(
        id="memory_graphiti_live_001",
        project_memory_space_id="project_graphiti_live_001",
        group_id="group_graphiti_live_001",
        thread_id="thread_graphiti_live_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.NOTE,
        title="Skyline codename owner",
        content="Alice owns the Skyline codename decision for the MemWing Graphiti live test.",
        summary=None,
        source_event_ids=("source_graphiti_live_001",),
        primary_source_event_id="source_graphiti_live_001",
        status=MemoryStatus.CANDIDATE,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
        original_score=0.9,
        half_life_days=180,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=NOW,
        activated_at=None,
        updated_at=NOW,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


def _graph_job() -> GraphWriteJob:
    return GraphWriteJob(
        id="graph_job_live_001",
        backend="graphiti",
        project_memory_space_id="project_graphiti_live_001",
        thread_id="thread_graphiti_live_001",
        saga_id=None,
        memory_id="memory_graphiti_live_001",
        source_event_ids=("source_graphiti_live_001",),
        route=MemoryRoute.GRAPH,
        status="pending",
        idempotency_key="graph:memory_graphiti_live_001",
        attempts=0,
        max_attempts=3,
        priority=100,
        next_run_at=NOW,
        dead_letter_reason=None,
        last_error=None,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
