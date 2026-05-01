import asyncio
import math
import os

import pytest

from memwing.infrastructure.llm.openclaw_runtime import OpenClawRuntimeEmbeddingClient


@pytest.mark.skipif(
    os.environ.get("MEMWING_LIVE_OPENCLAW_EMBEDDING") != "1",
    reason="set MEMWING_LIVE_OPENCLAW_EMBEDDING=1 to run OpenClaw runtime embedding smoke test",
)
def test_openclaw_runtime_embedding_live_returns_vectors() -> None:
    client = OpenClawRuntimeEmbeddingClient.from_env()

    async def scenario():
        return await client.embed_batch(
            (
                "MemWing OpenClaw embedding live smoke one",
                "MemWing OpenClaw embedding live smoke two",
            )
        )

    vectors = asyncio.run(scenario())

    assert len(vectors) == 2
    assert len(vectors[0]) > 0
    assert len(vectors[1]) == len(vectors[0])
    assert all(math.isfinite(value) for vector in vectors for value in vector)
    assert any(value != 0 for value in vectors[0])
