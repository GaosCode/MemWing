import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from memwing.core.memory_search import MemorySearchQuery
from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.evidence.qdrant_index import QdrantEvidenceIndex


def test_qdrant_evidence_index_upserts_source_event_payload() -> None:
    async def run() -> None:
        client = FakeQdrantClient()
        index = QdrantEvidenceIndex(
            client=client,
            embedding_client=FakeEmbeddingClient((0.1, 0.2)),
            collection="memwing_evidence",
            vector_size=2,
        )

        await index.index_source_event(_source_event(), _scope())

        assert client.created_collections == ["memwing_evidence"]
        point = client.upserts[0][0]
        assert point.vector == [0.1, 0.2]
        assert point.payload["source_event_id"] == "source_event_001"
        assert point.payload["project_memory_space_id"] == "project_001"
        assert point.payload["group_id"] == "group_001"
        assert point.payload["thread_id"] == "thread_001"
        assert point.payload["source_kind"] == "openclaw"
        assert point.payload["redacted"] is False
        assert point.payload["text"] == "负责人是沈南。"

    asyncio.run(run())


def test_qdrant_evidence_index_search_filters_by_effective_scope() -> None:
    async def run() -> None:
        client = FakeQdrantClient(collection_exists=True)
        client.query_points_response = [
            FakeScoredPoint(
                id="point_001",
                score=0.87,
                payload={
                    "source_event_id": "source_event_001",
                    "text": "负责人是沈南。",
                    "source_kind": "openclaw",
                    "content_hash": "hash",
                    "chunk_index": 0,
                },
            )
        ]
        index = QdrantEvidenceIndex(
            client=client,
            embedding_client=FakeEmbeddingClient((0.1, 0.2)),
            collection="memwing_evidence",
            vector_size=2,
        )

        result = await index.search(
            MemorySearchQuery(query="负责人", scope=_scope(), limit=5, trace_id="trace_001")
        )

        assert result.trace_id == "trace_001"
        assert result.results[0].source == "evidence_index"
        assert result.results[0].source_event_ids == ("source_event_001",)
        assert result.results[0].score == 0.87
        query_filter = client.query_filters[0]
        conditions = {condition.key: condition for condition in query_filter.must}
        assert conditions["project_memory_space_id"].match.value == "project_001"
        assert conditions["group_id"].match.value == "group_001"
        assert conditions["thread_id"].match.value == "thread_001"
        assert conditions["redacted"].match.value is False

    asyncio.run(run())


def test_qdrant_evidence_index_marks_source_redacted_by_scope() -> None:
    async def run() -> None:
        client = FakeQdrantClient(collection_exists=True)
        index = QdrantEvidenceIndex(
            client=client,
            embedding_client=FakeEmbeddingClient((0.1, 0.2)),
            collection="memwing_evidence",
            vector_size=2,
        )

        await index.mark_source_redacted("source_event_001", _scope())

        assert client.set_payloads[0]["payload"] == {"redacted": True}
        conditions = {condition.key: condition for condition in client.set_payloads[0]["points"].must}
        assert conditions["source_event_id"].match.value == "source_event_001"
        assert conditions["project_memory_space_id"].match.value == "project_001"

    asyncio.run(run())


class FakeEmbeddingClient:
    def __init__(self, vector: tuple[float, ...]) -> None:
        self.vector = vector

    async def embed(self, input: str) -> tuple[float, ...]:
        return self.vector

    async def embed_batch(self, inputs: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(self.vector for _input in inputs)


class FakeQdrantClient:
    def __init__(self, *, collection_exists: bool = False) -> None:
        self._collection_exists = collection_exists
        self.created_collections: list[str] = []
        self.upserts = []
        self.query_filters = []
        self.query_points_response = []
        self.set_payloads = []

    async def collection_exists(self, collection_name: str) -> bool:
        return self._collection_exists or collection_name in self.created_collections

    async def create_collection(self, *, collection_name, vectors_config):
        self.created_collections.append(collection_name)
        self.vectors_config = vectors_config

    async def upsert(self, *, collection_name, points, wait=True):
        self.upserts.append(points)

    async def query_points(
        self,
        *,
        collection_name,
        query,
        query_filter,
        limit,
        with_payload=True,
    ):
        self.query_filters.append(query_filter)
        return self.query_points_response[:limit]

    async def set_payload(self, *, collection_name, payload, points, wait=True):
        self.set_payloads.append({"payload": payload, "points": points})

    async def close(self) -> None:
        pass


@dataclass(frozen=True)
class FakeScoredPoint:
    id: str
    score: float
    payload: dict[str, object]


def _scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=False,
        cross_group_allowed=True,
    )


def _source_event() -> SourceEvent:
    return SourceEvent(
        id="source_event_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="author_001",
        author_name="周明",
        source_type="openclaw",
        content="负责人是沈南。",
        content_preview="负责人是沈南。",
        source_url=None,
        event_time=datetime(2026, 5, 2, 1, 0, tzinfo=UTC),
        raw_payload_hash="hash",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=datetime(2026, 5, 2, 1, 1, tzinfo=UTC),
    )
