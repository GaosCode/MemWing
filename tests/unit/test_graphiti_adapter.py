from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from memwing.core.models import (
    GraphWriteJob,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    SourceEvent,
)
from memwing.core.memory_search import MemorySearchQuery
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.graph.graphiti_adapter import (
    GraphitiAdapter,
    GraphitiConnectionConfig,
)
from memwing.infrastructure.graph.graphiti_embedder import GraphitiMemWingEmbedder
from memwing.infrastructure.graph.graphiti_llm import GraphitiMemWingLLMClient
from memwing.infrastructure.graph.graphiti_reranker import GraphitiNoProviderReranker
from memwing.ports.graph_backend import GraphWriteRequest
from memwing.ports.model_runtime import LLMModelRequest, LLMModelResponse


NOW = datetime(2026, 5, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FakeEdge:
    uuid: str
    fact: str
    episodes: list[str]
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
    attributes: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class FakeEpisode:
    uuid: str


@dataclass(frozen=True, slots=True)
class FakeAddEpisodeResult:
    episode: FakeEpisode
    edges: list[FakeEdge]


class FakeGraphiti:
    def __init__(self) -> None:
        self.add_episode_calls: list[dict[str, object]] = []
        self.search_calls: list[dict[str, object]] = []

    async def add_episode(self, **kwargs: object) -> FakeAddEpisodeResult:
        self.add_episode_calls.append(kwargs)
        return FakeAddEpisodeResult(
            episode=FakeEpisode(uuid="episode_001"),
            edges=[
                FakeEdge(
                    uuid="edge_001",
                    fact="Ada owns the roadmap.",
                    episodes=["episode_001"],
                    attributes={"confidence": 0.87},
                )
            ],
        )

    async def search(
        self,
        query: str,
        group_ids: list[str],
        num_results: int,
    ) -> list[FakeEdge]:
        self.search_calls.append(
            {"query": query, "group_ids": group_ids, "num_results": num_results}
        )
        return [
            FakeEdge(
                uuid="edge_002",
                fact="The roadmap is due Friday.",
                episodes=["episode_002"],
            )
        ]


class FakeLLMClient:
    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        return LLMModelResponse(text='{"ok":true}', provider="fake", model="fake")


class FakeEmbeddingClient:
    async def embed(self, input: str) -> tuple[float, ...]:
        return (1.0,)

    async def embed_batch(self, inputs: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple((float(index),) for index, _ in enumerate(inputs))


def test_graphiti_adapter_factory_injects_memwing_model_clients() -> None:
    constructed: list[dict[str, object]] = []

    def fake_factory(**kwargs: object) -> FakeGraphiti:
        constructed.append(kwargs)
        return FakeGraphiti()

    llm_client = GraphitiMemWingLLMClient(FakeLLMClient())
    embedder = GraphitiMemWingEmbedder(FakeEmbeddingClient())
    cross_encoder = GraphitiNoProviderReranker()

    adapter = GraphitiAdapter.from_clients(
        GraphitiConnectionConfig(uri="bolt://neo4j", user="neo4j", password="secret"),
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
        graphiti_factory=fake_factory,
    )

    assert isinstance(adapter, GraphitiAdapter)
    assert constructed == [
        {
            "uri": "bolt://neo4j",
            "user": "neo4j",
            "password": "secret",
            "llm_client": llm_client,
            "embedder": embedder,
            "cross_encoder": cross_encoder,
            "store_raw_episode_content": True,
        }
    ]


def test_graphiti_adapter_factory_requires_all_model_clients() -> None:
    with pytest.raises(ValueError, match="llm_client, embedder, and cross_encoder"):
        GraphitiAdapter.from_clients(
            GraphitiConnectionConfig(uri="bolt://neo4j"),
            llm_client=None,
            embedder=GraphitiMemWingEmbedder(FakeEmbeddingClient()),
            cross_encoder=GraphitiNoProviderReranker(),
            graphiti_factory=lambda **kwargs: FakeGraphiti(),
        )


def test_graphiti_adapter_ingests_graph_job_through_add_episode() -> None:
    graphiti = FakeGraphiti()
    adapter = GraphitiAdapter(graphiti)

    async def scenario():
        return await adapter.ingest_graph_job(
            GraphWriteRequest(
                job=_graph_job(),
                memory_item=_memory_item(),
                source_events=(_source_event(),),
            )
        )

    result = asyncio.run(scenario())

    assert graphiti.add_episode_calls[0]["name"] == "Decision: roadmap owner"
    assert graphiti.add_episode_calls[0]["episode_body"] == "Ada owns the roadmap."
    assert graphiti.add_episode_calls[0]["source_description"] == "MemWing graph write job"
    assert graphiti.add_episode_calls[0]["group_id"] == "project_001"
    assert "uuid" not in graphiti.add_episode_calls[0]
    assert result.backend == "graphiti"
    assert result.backend_episode_refs == ("episode_001",)
    assert result.backend_fact_refs == ("edge_001",)
    assert result.facts[0].fact_text == "Ada owns the roadmap."


def test_graphiti_adapter_search_maps_edges_to_memory_results() -> None:
    graphiti = FakeGraphiti()
    adapter = GraphitiAdapter(graphiti)
    query = MemorySearchQuery(
        query="roadmap",
        scope=EffectiveScope(
            project_memory_space_id="project_001",
            group_ids=("group_001",),
            thread_id=None,
            shared_group_id=None,
            safe_mode_enabled=False,
            cross_group_allowed=True,
        ),
        limit=3,
    )

    async def scenario():
        return await adapter.search_current(query)

    result = asyncio.run(scenario())

    assert graphiti.search_calls == [
        {"query": "roadmap", "group_ids": ["project_001"], "num_results": 3}
    ]
    assert result.contexts == ("The roadmap is due Friday.",)
    assert result.results[0].id == "edge_002"
    assert result.results[0].source == "graph"
    assert result.results[0].metadata["backend"] == "graphiti"


def test_graphiti_adapter_source_redaction_marker_is_explicitly_unsupported() -> None:
    adapter = GraphitiAdapter(FakeGraphiti())

    async def scenario() -> None:
        await adapter.mark_source_redacted(
            "source_001",
            EffectiveScope(
                project_memory_space_id="project_001",
                group_ids=("group_001",),
                thread_id=None,
                shared_group_id=None,
                safe_mode_enabled=False,
                cross_group_allowed=True,
            ),
        )

    with pytest.raises(NotImplementedError, match="source redaction marker"):
        asyncio.run(scenario())


def _source_event() -> SourceEvent:
    return SourceEvent(
        id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content="Ada owns the roadmap.",
        content_preview="Ada owns the roadmap.",
        source_url=None,
        event_time=NOW,
        raw_payload_hash="hash",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
        runtime_event_idempotency_key="runtime-key",
    )


def _memory_item() -> MemoryItem:
    return MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Decision: roadmap owner",
        content="Ada owns the roadmap.",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.CANDIDATE,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
        original_score=0.9,
        half_life_days=30,
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
        id="graph_job_001",
        backend="graphiti",
        project_memory_space_id="project_001",
        thread_id="thread_001",
        saga_id=None,
        memory_id="memory_001",
        source_event_ids=("source_001",),
        route=MemoryRoute.GRAPH,
        status="pending",
        idempotency_key="graph:memory_001",
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
