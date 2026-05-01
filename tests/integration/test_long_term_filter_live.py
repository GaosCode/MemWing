from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import os

import pytest

from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.llm.long_term_filter import MemWingLongTermFilterAdapter
from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawRuntimeConfig,
    OpenClawRuntimeLLMClient,
)
from memwing.ports.llm_filter import LongTermFilterRequest


@pytest.mark.skipif(
    os.environ.get("MEMWING_LIVE_OPENCLAW_MEMORY_CHAIN") != "1",
    reason="set MEMWING_LIVE_OPENCLAW_MEMORY_CHAIN=1 to run LongTermFilter live smoke",
)
def test_openclaw_long_term_filter_live_smoke_extracts_explicit_memory() -> None:
    adapter = MemWingLongTermFilterAdapter(_openclaw_llm())

    async def scenario():
        return await adapter.filter_events(
            LongTermFilterRequest(
                scope=_scope(),
                source_events=(_source_event(),),
                recent_page_memory=None,
                history_items=(),
                evidence_snippets=(),
                trace_id="long_term_filter_live_eval",
            )
        )

    candidates = asyncio.run(scenario())

    assert candidates
    assert any("event_live_filter_001" in candidate.source_event_ids for candidate in candidates)
    assert any("Skyline" in candidate.content or "Skyline" in candidate.title for candidate in candidates)


def _openclaw_llm() -> OpenClawRuntimeLLMClient:
    resolver = MemWingModelConfigResolver.from_env()
    selection = resolver.selection_for("long_term_filter")
    return OpenClawRuntimeLLMClient(OpenClawRuntimeConfig.from_env_model_selection(selection))


def _scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_live_filter_001",
        group_ids=("group_live_filter_001",),
        thread_id="thread_live_filter_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )


def _source_event() -> SourceEvent:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return SourceEvent(
        id="event_live_filter_001",
        project_memory_space_id="project_live_filter_001",
        group_id="group_live_filter_001",
        thread_id="thread_live_filter_001",
        shared_group_id=None,
        author_id="user_live_filter_001",
        author_name="Alice",
        source_type="message",
        content=(
            "Please remember this as long-term project memory: "
            "the durable project codename is Skyline."
        ),
        content_preview="The durable project codename is Skyline.",
        source_url=None,
        event_time=now,
        raw_payload_hash="hash_live_filter_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=True,
        created_at=now,
    )
