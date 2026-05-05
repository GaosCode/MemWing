from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys
from types import SimpleNamespace


VENDORED_PARENT = Path(__file__).resolve().parents[2] / "memwing/infrastructure/graph"
if str(VENDORED_PARENT) not in sys.path:
    sys.path.insert(0, str(VENDORED_PARENT))

from graphiti_core.graphiti import Graphiti  # noqa: E402
from graphiti_core.nodes import EpisodeType  # noqa: E402
from graphiti_core.utils.bulk_utils import RawEpisode  # noqa: E402


NOW = datetime(2026, 5, 1, tzinfo=UTC)


def test_semantic_bulk_retrieves_existing_previous_context_once() -> None:
    graphiti = object.__new__(Graphiti)
    retrieve_calls: list[dict[str, object]] = []
    add_calls: list[dict[str, object]] = []

    async def retrieve_episodes(reference_time, *, last_n, group_ids, source):
        retrieve_calls.append(
            {
                "reference_time": reference_time,
                "last_n": last_n,
                "group_ids": group_ids,
                "source": source,
            }
        )
        return [SimpleNamespace(uuid="existing_episode_001")]

    async def add_episode(**kwargs):
        add_calls.append(kwargs)
        return SimpleNamespace(episode=SimpleNamespace(uuid=kwargs["uuid"]))

    graphiti.retrieve_episodes = retrieve_episodes
    graphiti.add_episode = add_episode

    episodes = [
        _raw_episode("first_episode", "First decision."),
        _raw_episode("second_episode", "Second decision."),
    ]

    results = asyncio.run(
        graphiti.add_episode_bulk_semantic(
            episodes,
            group_id="project_001",
        )
    )

    assert [result.episode.uuid for result in results] == ["first_episode", "second_episode"]
    assert len(retrieve_calls) == 1
    assert retrieve_calls[0]["reference_time"] == NOW
    assert add_calls[0]["previous_episode_uuids"] == ["existing_episode_001"]
    assert add_calls[0]["saga_previous_episode_uuid"] == "existing_episode_001"
    assert add_calls[1]["previous_episode_uuids"] == ["first_episode"]
    assert add_calls[1]["saga_previous_episode_uuid"] == "first_episode"


def _raw_episode(uuid: str, content: str) -> RawEpisode:
    return RawEpisode(
        name=uuid,
        uuid=uuid,
        content=content,
        source_description="MemWing graph write job",
        source=EpisodeType.message,
        reference_time=NOW,
    )
