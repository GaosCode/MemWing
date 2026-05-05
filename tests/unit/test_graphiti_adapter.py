from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import re

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
from memwing.ports.graph_backend import GraphWriteBatchRequest, GraphWriteRequest
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
        episode_uuid = kwargs.get("uuid")
        if not isinstance(episode_uuid, str):
            episode_uuid = "episode_001"
        return FakeAddEpisodeResult(
            episode=FakeEpisode(uuid=episode_uuid),
            edges=[
                FakeEdge(
                    uuid="edge_001",
                    fact="Ada owns the roadmap.",
                    episodes=[episode_uuid],
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
    assert graphiti.add_episode_calls[0]["uuid"]
    assert graphiti.add_episode_calls[0]["previous_episode_uuids"] is None
    assert result.backend == "graphiti"
    assert result.backend_episode_refs == (graphiti.add_episode_calls[0]["uuid"],)
    assert result.backend_fact_refs == ("edge_001",)
    assert result.facts[0].fact_text == "Ada owns the roadmap."


def test_graphiti_adapter_ordered_batch_uses_stable_uuid_and_previous_episode_context() -> None:
    graphiti = FakeGraphiti()
    adapter = GraphitiAdapter(graphiti)
    first_job = _graph_job("graph_job_001", memory_id="memory_001", source_event_id="source_001")
    second_job = _graph_job("graph_job_002", memory_id="memory_002", source_event_id="source_002")
    first_memory = _memory_item(
        memory_id="memory_001",
        source_event_id="source_001",
        content="First decision.",
    )
    second_memory = _memory_item(
        memory_id="memory_002",
        source_event_id="source_002",
        content="Second decision.",
    )

    async def scenario():
        return await adapter.ingest_graph_jobs(
            GraphWriteBatchRequest(
                requests=(
                    GraphWriteRequest(
                        job=second_job,
                        memory_item=second_memory,
                        source_events=(_source_event("source_002"),),
                    ),
                    GraphWriteRequest(
                        job=first_job,
                        memory_item=first_memory,
                        source_events=(_source_event("source_001"),),
                    ),
                )
            )
        )

    result = asyncio.run(scenario())

    assert tuple(item.job_id for item in result.items) == ("graph_job_001", "graph_job_002")
    assert len(graphiti.add_episode_calls) == 2
    first_uuid = graphiti.add_episode_calls[0]["uuid"]
    assert graphiti.add_episode_calls[0]["previous_episode_uuids"] is None
    assert graphiti.add_episode_calls[1]["previous_episode_uuids"] == [first_uuid]
    assert graphiti.add_episode_calls[0]["uuid"] != graphiti.add_episode_calls[1]["uuid"]


def test_graphiti_adapter_reuses_stable_episode_uuid_for_job_retry() -> None:
    graphiti = FakeGraphiti()
    adapter = GraphitiAdapter(graphiti)
    request = GraphWriteRequest(
        job=_graph_job(),
        memory_item=_memory_item(),
        source_events=(_source_event(),),
    )

    async def scenario():
        first = await adapter.ingest_graph_job(request)
        retry = await adapter.ingest_graph_job(request)
        return first, retry

    first, retry = asyncio.run(scenario())

    assert graphiti.add_episode_calls[0]["uuid"] == graphiti.add_episode_calls[1]["uuid"]
    assert first.backend_episode_refs == retry.backend_episode_refs


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
    assert result.results[0].source == "graph_backend"
    assert result.results[0].metadata["backend"] == "graphiti"


def test_graphiti_adapter_maps_invalid_project_id_to_safe_group_id() -> None:
    graphiti = FakeGraphiti()
    adapter = GraphitiAdapter(graphiti)
    query = MemorySearchQuery(
        query="roadmap",
        scope=EffectiveScope(
            project_memory_space_id="benchmark:20260503-024019:bs001",
            group_ids=("benchmark:bs001",),
            thread_id=None,
            shared_group_id=None,
            safe_mode_enabled=False,
            cross_group_allowed=True,
        ),
        limit=3,
    )

    async def scenario():
        return await adapter.search_current(query)

    asyncio.run(scenario())

    mapped_group_id = graphiti.search_calls[0]["group_ids"][0]
    assert mapped_group_id.startswith("mw_benchmark_20260503-024019_bs001_")
    assert ":" not in mapped_group_id
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", mapped_group_id)


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


def _source_event(source_event_id: str = "source_001") -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
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


def _memory_item(
    *,
    memory_id: str = "memory_001",
    source_event_id: str = "source_001",
    content: str = "Ada owns the roadmap.",
) -> MemoryItem:
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Decision: roadmap owner",
        content=content,
        summary=None,
        source_event_ids=(source_event_id,),
        primary_source_event_id=source_event_id,
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


def _graph_job(
    job_id: str = "graph_job_001",
    *,
    memory_id: str = "memory_001",
    source_event_id: str = "source_001",
) -> GraphWriteJob:
    return GraphWriteJob(
        id=job_id,
        backend="graphiti",
        serialization_key="backend:graphiti:project:project_001",
        project_memory_space_id="project_001",
        thread_id="thread_001",
        saga_id=None,
        memory_id=memory_id,
        source_event_ids=(source_event_id,),
        route=MemoryRoute.GRAPH,
        status="pending",
        idempotency_key=f"graph:{memory_id}",
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
