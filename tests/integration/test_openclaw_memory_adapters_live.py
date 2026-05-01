from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import os

import pytest

from memwing.core.models import PageMemory, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.llm.long_term_filter import MemWingLongTermFilterAdapter
from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawRuntimeConfig,
    OpenClawRuntimeLLMClient,
)
from memwing.infrastructure.llm.page_memory_synthesis import MemWingPageMemorySynthesisAdapter
from memwing.ports.llm_filter import LongTermFilterRequest
from memwing.ports.model_runtime import MemWingModelRole
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest


@pytest.mark.skipif(
    os.environ.get("MEMWING_LIVE_OPENCLAW_MEMORY_CHAIN") != "1",
    reason="set MEMWING_LIVE_OPENCLAW_MEMORY_CHAIN=1 to run Page Memory and LongTermFilter live smoke",
)
def test_openclaw_page_memory_and_long_term_filter_live_chain() -> None:
    scope = _scope()
    source_event = _source_event()
    page_adapter = MemWingPageMemorySynthesisAdapter(_openclaw_llm_for("page_memory"))
    filter_adapter = MemWingLongTermFilterAdapter(_openclaw_llm_for("long_term_filter"))

    async def scenario():
        synthesis = await page_adapter.synthesize(
            PageMemorySynthesisRequest(
                scope=scope,
                source_events=(source_event,),
                existing_page=None,
                linked_memory_items=(),
            )
        )
        recent_page = PageMemory(
            id="page_live_001",
            project_memory_space_id=scope.project_memory_space_id,
            group_id="group_live_001",
            thread_id=scope.thread_id,
            shared_group_id=scope.shared_group_id,
            scope_type="thread",
            scope_id=scope.thread_id or "thread_live_001",
            title=synthesis.title,
            brief=synthesis.brief,
            topics=synthesis.topics,
            open_questions=synthesis.open_questions,
            next_steps=synthesis.next_steps,
            source_event_ids=synthesis.source_event_ids,
            linked_memory_item_ids=synthesis.linked_memory_item_ids,
            version=1,
            needs_rebuild=False,
            created_at=source_event.created_at,
            updated_at=source_event.created_at,
        )
        candidates = await filter_adapter.filter_events(
            LongTermFilterRequest(
                scope=scope,
                source_events=(source_event,),
                recent_page_memory=recent_page,
                history_items=(),
                evidence_snippets=(),
                trace_id="openclaw_memory_chain_live",
            )
        )
        return synthesis, candidates

    synthesis, candidates = asyncio.run(scenario())

    assert synthesis.title.strip()
    assert synthesis.topics
    assert "event_live_001" in synthesis.source_event_ids
    assert candidates
    assert "event_live_001" in candidates[0].source_event_ids
    assert candidates[0].title.strip()
    assert candidates[0].content.strip()


def _openclaw_llm_for(role: MemWingModelRole) -> OpenClawRuntimeLLMClient:
    resolver = MemWingModelConfigResolver.from_env()
    selection = resolver.selection_for(role)
    return OpenClawRuntimeLLMClient(OpenClawRuntimeConfig.from_env_model_selection(selection))


def _scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_live_001",
        group_ids=("group_live_001",),
        thread_id="thread_live_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )


def _source_event() -> SourceEvent:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return SourceEvent(
        id="event_live_001",
        project_memory_space_id="project_live_001",
        group_id="group_live_001",
        thread_id="thread_live_001",
        shared_group_id=None,
        author_id="user_live_001",
        author_name="Alice",
        source_type="message",
        content=(
            "Please remember this as long-term project memory: "
            "the durable project codename is Skyline and status updates must use it."
        ),
        content_preview="The durable project codename is Skyline.",
        source_url=None,
        event_time=now,
        raw_payload_hash="hash_live_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=True,
        created_at=now,
    )
