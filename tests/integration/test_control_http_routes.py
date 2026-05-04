from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
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
    PushCandidate,
    SourceEvent,
)
from memwing.core.platform import PlatformSendResult
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


def test_control_http_manual_memory_create_writes_source_event_without_runtime_binding() -> None:
    store = _store()
    app = create_app(runtime_context_factory=_context(store))

    with TestClient(app) as client:
        response = client.post(
            "/v1/control/memories/manual",
            params={"project_memory_space_id": "project_001"},
            json={
                **_envelope("manual-memory-001"),
                "title": "Manual memory title",
                "content": "Manual memory content.",
                "source_url": "https://memwing.local/manual",
            },
        )
        duplicate_response = client.post(
            "/v1/control/memories/manual",
            params={"project_memory_space_id": "project_001"},
            json={
                **_envelope("manual-memory-001"),
                "title": "Manual memory title",
                "content": "Manual memory content.",
                "source_url": "https://memwing.local/manual",
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["duplicate_of"] is None
    assert body["trace_id"] == "trace_manual-memory-001"
    assert duplicate_response.status_code == 202
    assert duplicate_response.json()["duplicate_of"] == body["source_event_id"]

    assert len(store.source_events) == 1
    source_event = store.source_events[0]
    assert source_event.id == body["source_event_id"]
    assert source_event.project_memory_space_id == "project_001"
    assert source_event.author_id == "user_001"
    assert source_event.source_type == "control.manual_memory"
    assert source_event.content == "Manual memory title\n\nManual memory content."
    assert source_event.source_url == "https://memwing.local/manual"
    assert source_event.metadata["source_ref"] == {"kind": "control", "actor_id": "user_001"}
    assert len(store.outbox_jobs) == 4
    assert store.audit_events[0].stage == "remember_event.captured"


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


def test_control_http_reads_source_events() -> None:
    store = _store()
    _seed_memory(store)
    app = create_app(runtime_context_factory=_context(store))

    with TestClient(app) as client:
        list_response = client.get(
            "/v1/control/source-events",
            params={"project_memory_space_id": "project_001", "limit": "20"},
        )
        detail_response = client.get(
            "/v1/control/source-events/source_001",
            params={"project_memory_space_id": "project_001"},
        )

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == "source_001"
    assert detail_response.status_code == 200
    assert detail_response.json()["source_event"]["content_preview"] == "Source content."
    assert detail_response.json()["memory_item_ids"] == ["memory_001"]


def test_control_http_sends_approved_push_candidate_to_platform() -> None:
    store = _store()
    connector = _RecordingPlatformConnector()
    _seed_approved_push(store)
    app = create_app(runtime_context_factory=_context(store, platform_connectors={"feishu": connector}))

    with TestClient(app) as client:
        response = client.post(
            "/v1/platforms/feishu/push-candidates/push_001/send",
            params={"project_memory_space_id": "project_001"},
            json=_envelope("send-push-001"),
        )

    assert response.status_code == 200
    assert response.json()["item"]["status"] == "sent"
    assert connector.sent == (
        (
            "push_001",
            "oc_group_001",
            "Push content.",
            "trace_send-push-001",
            "Push title",
            "decision_card",
        ),
    )


def _context(
    store: InMemoryDataStore,
    *,
    platform_connectors: Mapping[str, object] | None = None,
):
    @asynccontextmanager
    async def factory() -> AsyncIterator[MemWingApiRuntimeContext]:
        yield MemWingApiRuntimeContext(
            runtime=_FakeRuntime(),
            control=ControlService(store, now=lambda: NOW, platform_connectors=platform_connectors),
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


def _seed_approved_push(store: InMemoryDataStore) -> None:
    import asyncio

    async def seed() -> None:
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(
                _source_event(
                    metadata={
                        "source_ref": {
                            "kind": "platform",
                            "platform": "feishu",
                            "tenant_id": "tenant_001",
                            "channel_id": "oc_group_001",
                            "thread_id": "thread_001",
                        }
                    }
                )
            )
            await tx.push_candidates.upsert(_push_candidate())

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


def _source_event(metadata: dict[str, object] | None = None) -> SourceEvent:
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
        metadata=metadata or {},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW - timedelta(days=1),
    )


def _push_candidate() -> PushCandidate:
    return PushCandidate(
        id="push_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        type="decision_card",
        title="Push title",
        content="Push content.",
        memory_item_ids=("memory_001",),
        source_event_ids=("source_001",),
        trigger_reason="manual_test",
        trigger_source="memory_item",
        priority=100,
        expires_at=None,
        status="approved",
        cooldown_key="decision_card:memory_001",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
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


class _RecordingPlatformConnector:
    def __init__(self) -> None:
        self.sent: tuple[tuple[str, str, str, str, str | None, str | None], ...] = ()

    async def verify_request(self, raw_request):
        raise AssertionError("verify_request should not be called")

    async def normalize_event(self, raw_event):
        raise AssertionError("normalize_event should not be called")

    async def send_candidate(self, candidate) -> PlatformSendResult:
        self.sent = (
            *self.sent,
            (
                candidate.id,
                candidate.platform_ref.channel_id,
                candidate.content,
                candidate.trace_id,
                candidate.title,
                candidate.kind,
            ),
        )
        return PlatformSendResult(
            candidate_id=candidate.id,
            delivered=True,
            trace_id=candidate.trace_id,
            provider_message_id="sent_001",
        )


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
