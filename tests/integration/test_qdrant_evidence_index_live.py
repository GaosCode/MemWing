import asyncio
from datetime import UTC, datetime
import os
from uuid import uuid4

import pytest

from memwing.core.memory_search import MemorySearchQuery
from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.evidence.qdrant_index import QdrantEvidenceIndex

qdrant_client = pytest.importorskip("qdrant_client")


def test_qdrant_evidence_index_live_round_trip() -> None:
    qdrant_url = os.environ.get("QDRANT_URL")
    if not qdrant_url:
        pytest.skip("set QDRANT_URL to run Qdrant evidence integration test")

    async def run() -> None:
        client = qdrant_client.AsyncQdrantClient(url=qdrant_url)
        try:
            try:
                await client.collection_exists("memwing_qdrant_reachable_probe")
            except Exception as exc:
                pytest.skip(f"Qdrant is not reachable at QDRANT_URL: {exc}")

            collection = f"memwing_evidence_test_{uuid4().hex}"
            index = QdrantEvidenceIndex(
                client=client,
                embedding_client=FakeEmbeddingClient(),
                collection=collection,
                vector_size=2,
            )
            await index.index_source_event(_source_event(), _scope())

            result = await index.search(
                MemorySearchQuery(query="负责人", scope=_scope(), limit=3, trace_id="trace_live")
            )

            assert result.results
            assert result.results[0].source == "evidence_index"
            assert result.results[0].source_event_ids == ("source_event_001",)
        finally:
            await client.close()

    asyncio.run(run())


class FakeEmbeddingClient:
    async def embed(self, input: str) -> tuple[float, ...]:
        return (1.0, 0.0)

    async def embed_batch(self, inputs: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple((1.0, 0.0) for _input in inputs)


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
