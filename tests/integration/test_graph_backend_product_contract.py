import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from memwing.core.memory_search import MemorySearchQuery
from memwing.core.models import (
    GraphWriteJob,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.graph.graphiti_adapter import GraphitiAdapter
from memwing.ports.graph_backend import GraphWriteRequest


NOW = datetime(2026, 5, 5, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _FakeEpisode:
    uuid: str


@dataclass(frozen=True, slots=True)
class _FakeEdge:
    uuid: str
    fact: str
    episodes: list[str]
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
    attributes: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class _FakeAddEpisodeResult:
    episode: _FakeEpisode
    edges: list[_FakeEdge]


class _FactUpdateGraphiti:
    async def add_episode(self, **kwargs: object) -> _FakeAddEpisodeResult:
        episode_uuid = kwargs["uuid"]
        assert isinstance(episode_uuid, str)
        return _FakeAddEpisodeResult(
            episode=_FakeEpisode(uuid=episode_uuid),
            edges=[
                _FakeEdge(
                    uuid="edge_current",
                    fact="Ada owns the roadmap.",
                    episodes=[episode_uuid],
                    valid_at=NOW,
                    attributes={"confidence": 0.9},
                ),
                _FakeEdge(
                    uuid="edge_stale",
                    fact="Grace owns the roadmap.",
                    episodes=["episode_old"],
                    valid_at=datetime(2026, 5, 1, tzinfo=UTC),
                    invalid_at=NOW,
                    expired_at=NOW,
                ),
            ],
        )

    async def search(self, query: str, group_ids: list[str], num_results: int) -> list[_FakeEdge]:
        return [
            _FakeEdge(
                uuid="edge_current",
                fact="Ada owns the roadmap.",
                episodes=["episode_current"],
                valid_at=NOW,
                attributes={"confidence": 0.9},
            )
        ]


class _TemporalConflictGraphiti:
    async def add_episode(self, **kwargs: object) -> _FakeAddEpisodeResult:
        episode_uuid = kwargs["uuid"]
        assert isinstance(episode_uuid, str)
        return _FakeAddEpisodeResult(episode=_FakeEpisode(uuid=episode_uuid), edges=[])

    async def search(self, query: str, group_ids: list[str], num_results: int) -> list[_FakeEdge]:
        return [
            _FakeEdge(
                uuid="edge_active",
                fact="The launch date is Friday.",
                episodes=["episode_active"],
                valid_at=datetime(2026, 5, 5, tzinfo=UTC),
                invalid_at=None,
            ),
            _FakeEdge(
                uuid="edge_superseded",
                fact="The launch date is Thursday.",
                episodes=["episode_superseded"],
                valid_at=datetime(2026, 5, 1, tzinfo=UTC),
                invalid_at=datetime(2026, 5, 5, tzinfo=UTC),
            ),
        ][:num_results]


def test_graphiti_adapter_product_contract_preserves_fact_update_invalidations() -> None:
    adapter = GraphitiAdapter(_FactUpdateGraphiti())

    async def scenario():
        return await adapter.ingest_graph_job(
            GraphWriteRequest(
                job=_graph_job(),
                memory_item=_memory_item(),
                source_events=(_source_event(),),
            )
        )

    result = asyncio.run(scenario())

    assert result.backend_episode_refs
    assert {fact.fact_id for fact in result.facts} == {"edge_current", "edge_stale"}
    assert tuple(fact.fact_id for fact in result.invalidated_facts) == ("edge_stale",)
    assert result.invalidated_facts[0].invalidated_at == NOW


def test_graphiti_adapter_product_contract_preserves_temporal_conflict_metadata() -> None:
    adapter = GraphitiAdapter(_TemporalConflictGraphiti())

    async def scenario():
        return await adapter.search_current(
            MemorySearchQuery(
                query="launch date",
                scope=EffectiveScope(
                    project_memory_space_id="project_001",
                    group_ids=("group_001",),
                    thread_id=None,
                    shared_group_id=None,
                    safe_mode_enabled=False,
                    cross_group_allowed=True,
                ),
                limit=2,
            )
        )

    result = asyncio.run(scenario())

    assert tuple(item.id for item in result.results) == ("edge_active", "edge_superseded")
    assert result.results[0].valid_to is None
    assert result.results[1].valid_to == datetime(2026, 5, 5, tzinfo=UTC)


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
        raw_payload_hash="hash_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
        runtime_event_idempotency_key="runtime-key-001",
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
        serialization_key="backend:graphiti:project:project_001",
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
