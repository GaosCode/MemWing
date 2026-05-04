from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from memwing.api.server import create_app
from memwing.application.control_service import ControlService
from memwing.application.scope_resolver import ScopeResolver
from memwing.application.source_redaction_service import SourceRedactionService
from memwing.bootstrap import MemWingApiRuntimeContext
from memwing.core.memory_access import MemoryAccessSearchResult
from memwing.core.models import (
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    PageMemory,
    PageMemoryTopic,
    SourceEvent,
)
from memwing.core.runtime import AgentContextResult, AgentRuntimeStatusResult, RememberEventResult
from memwing.core.scope import ProjectMemorySpace
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.agent_runtime import AgentRuntimePort


NOW = datetime(2026, 5, 4, tzinfo=UTC)


def test_control_http_lists_details_and_mutates_memories() -> None:
    store = _store()
    _seed_memory(store)
    app = create_app(runtime_context_factory=_context(store))

    with TestClient(app) as client:
        list_response = client.get(
            "/v1/control/memories",
            params={"project_memory_space_id": "project_001", "limit": "20"},
        )
        detail_response = client.get(
            "/v1/control/memories/memory_001",
            params={"project_memory_space_id": "project_001"},
        )
        confirm_response = client.post(
            "/v1/memory/memory_001/confirm",
            params={"project_memory_space_id": "project_001"},
            json=_envelope("confirm-memory-001"),
        )
        edit_response = client.patch(
            "/v1/memory/memory_001",
            params={"project_memory_space_id": "project_001"},
            json={
                **_envelope("edit-memory-001"),
                "title": "Edited memory title",
                "content": "Edited memory content.",
                "summary": "Edited summary.",
            },
        )

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == "memory_001"
    assert detail_response.status_code == 200
    assert detail_response.json()["item"]["status"] == "candidate"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["ok"] is True
    assert confirm_response.json()["item"]["item"]["status"] == "active"
    assert edit_response.status_code == 200
    assert edit_response.json()["item"]["item"]["title"] == "Edited memory title"


def test_control_http_edits_pages_and_purges_sources() -> None:
    store = _store()
    _seed_memory(store)
    _seed_page(store)
    app = create_app(runtime_context_factory=_context(store))

    with TestClient(app) as client:
        page_response = client.patch(
            "/v1/control/pages/page_001",
            params={"project_memory_space_id": "project_001"},
            json={
                **_envelope("edit-page-001"),
                "title": "Edited page title",
                "brief": "Edited page brief.",
            },
        )
        purge_response = client.post(
            "/v1/source-events/source_001/purge",
            params={"project_memory_space_id": "project_001"},
            json={
                **_envelope("purge-source-001"),
                "purge_level": "memwing_redaction",
            },
        )

    assert page_response.status_code == 200
    assert page_response.json()["item"]["page"]["title"] == "Edited page title"
    assert purge_response.status_code == 200
    assert purge_response.json()["item"]["source_event"]["purge_level"] == "memwing_redaction"
    assert purge_response.json()["item"]["affected_memory_item_ids"] == ["memory_001"]


def _context(store: InMemoryDataStore):
    @asynccontextmanager
    async def factory() -> AsyncIterator[MemWingApiRuntimeContext]:
        yield MemWingApiRuntimeContext(
            runtime=_FakeRuntime(),
            control=ControlService(store, now=lambda: NOW),
            control_scope_resolver=ScopeResolver(store),
            source_redaction=SourceRedactionService(store, now=lambda: NOW),
        )

    return factory


def _store() -> InMemoryDataStore:
    store = InMemoryDataStore()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Demo",
            default_safe_mode_enabled=False,
        )
    )
    return store


def _seed_memory(store: InMemoryDataStore) -> None:
    import asyncio

    async def seed() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event())
            await tx.memory_items.upsert(_memory_item())

    asyncio.run(seed())


def _seed_page(store: InMemoryDataStore) -> None:
    import asyncio

    async def seed() -> None:
        async with store.transaction() as tx:
            await tx.memory_pages.upsert(_page())

    asyncio.run(seed())


def _memory_item() -> MemoryItem:
    return MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Candidate memory",
        content="Candidate memory content.",
        summary="Candidate summary.",
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.CANDIDATE,
        event_time=NOW - timedelta(days=1),
        valid_from=None,
        valid_to=None,
        original_score=0.8,
        half_life_days=10,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=NOW - timedelta(days=1),
        activated_at=None,
        updated_at=NOW - timedelta(days=1),
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )


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
        content="Source content.",
        content_preview="Source content.",
        source_url=None,
        event_time=NOW - timedelta(days=1),
        raw_payload_hash="hash_source_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW - timedelta(days=1),
    )


def _page() -> PageMemory:
    return PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Current page title",
        brief="Current page brief.",
        topics=(PageMemoryTopic("Demo", "Summary", ("source_001",), ("memory_001",)),),
        open_questions=(),
        next_steps=(),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
        version=1,
        needs_rebuild=False,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


def _envelope(idempotency_key: str) -> dict[str, str]:
    return {
        "actor_id": "user_001",
        "reason": "integration test mutation",
        "idempotency_key": idempotency_key,
        "trace_id": f"trace_{idempotency_key}",
    }


class _FakeRuntime(AgentRuntimePort):
    async def build_context(self, request):
        return AgentContextResult(
            messages=None,
            system_prompt_addition="",
            context_blocks=(),
            estimated_tokens=0,
            trace_id="trace-context",
        )

    async def remember_runtime_event(self, event):
        return RememberEventResult(accepted=True, source_event_id="source_001", trace_id="trace")

    async def knowledge_search(self, query):
        return MemoryAccessSearchResult(contexts=(), results=(), next_cursor=None, trace_id="trace")

    async def knowledge_get(self, request):
        raise AssertionError("not used")

    async def knowledge_explain(self, request):
        raise AssertionError("not used")

    async def runtime_status(self, request):
        return AgentRuntimeStatusResult(
            runtime_ref=request.runtime_ref,
            healthy=True,
            capabilities=(),
            trace_id="trace-status",
        )
