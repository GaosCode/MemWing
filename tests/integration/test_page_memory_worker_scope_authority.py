import asyncio
from datetime import UTC, datetime

from memwing.application.page_memory_service import PageMemoryService
from memwing.application.scope_resolver import ResolvedScope
from memwing.core.models import (
    OutboxJob,
    PageMemory,
    PageMemorySynthesis,
    PageMemoryTopic,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest
from memwing.workers.page_memory_worker import PageMemoryWorker


NOW = datetime(2026, 4, 28, 12, tzinfo=UTC)


def test_worker_rebuild_uses_scope_resolver_as_authority() -> None:
    store = InMemoryDataStore()
    authority_scope = EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_authority",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )
    _seed_source_events(
        store,
        _source_event(
            "source_authority",
            "Only the resolver-authorized group should feed this rebuild.",
            group_id="group_authority",
        ),
    )
    _seed_pages(
        store,
        _page_memory(
            "page_001",
            group_id="group_persisted",
            needs_rebuild=True,
        ),
    )
    resolver = _RecordingPageMemoryRebuildScopeResolver(authority_scope)
    synthesis = _EchoSourceEventSynthesis()
    service = PageMemoryService(store, synthesis, clock=_FixedClock(NOW))
    worker = PageMemoryWorker(store, service, scope_resolver=resolver)

    result = asyncio.run(worker.maybe_rebuild(_outbox_job("job_001")))

    assert result.rebuilt == 1
    assert resolver.pages == ("page_001",)
    assert synthesis.requests[0].scope == authority_scope
    assert tuple(event.id for event in synthesis.requests[0].source_events) == (
        "source_authority",
    )


def _seed_source_events(
    store: InMemoryDataStore,
    *events: SourceEvent,
) -> InMemoryDataStore:
    async def seed() -> None:
        async with store.transaction() as tx:
            for event in events:
                await tx.source_events.insert_if_absent(event)

    asyncio.run(seed())
    return store


def _seed_pages(
    store: InMemoryDataStore,
    *pages: PageMemory,
) -> InMemoryDataStore:
    async def seed() -> None:
        async with store.transaction() as tx:
            for page in pages:
                await tx.memory_pages.upsert(page)

    asyncio.run(seed())
    return store


def _source_event(
    source_event_id: str,
    content: str,
    *,
    group_id: str,
) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id=group_id,
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content=content,
        content_preview=content,
        source_url=None,
        event_time=NOW,
        raw_payload_hash=f"hash_{source_event_id}",
        metadata={"message_id": source_event_id},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
        runtime_event_idempotency_key=f"runtime_{source_event_id}",
    )


def _page_memory(
    page_id: str,
    *,
    group_id: str,
    needs_rebuild: bool,
) -> PageMemory:
    return PageMemory(
        id=page_id,
        project_memory_space_id="project_001",
        group_id=group_id,
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Existing page",
        brief="Existing page content.",
        topics=(
            PageMemoryTopic(
                title="Existing topic",
                summary="Existing topic summary.",
                source_event_ids=("source_authority",),
                linked_memory_item_ids=(),
            ),
        ),
        open_questions=(),
        next_steps=(),
        source_event_ids=("source_authority",),
        linked_memory_item_ids=(),
        version=1,
        needs_rebuild=needs_rebuild,
        created_at=NOW,
        updated_at=NOW,
    )


def _outbox_job(job_id: str) -> OutboxJob:
    return OutboxJob(
        id=job_id,
        project_memory_space_id="project_001",
        source_event_id="source_authority",
        job_type="page_memory.maybe_rebuild",
        payload_json={"source_event_id": "source_authority"},
        status="pending",
        idempotency_key=f"page_memory.maybe_rebuild:{job_id}",
        aggregate_key="source_authority",
        attempts=0,
        max_attempts=3,
        priority=100,
        next_run_at=NOW,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        last_error=None,
        dead_letter_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _RecordingPageMemoryRebuildScopeResolver:
    def __init__(self, scope: EffectiveScope) -> None:
        self._scope = scope
        self.pages: tuple[str, ...] = ()

    async def resolve_page_memory_rebuild(self, page: PageMemory) -> ResolvedScope:
        self.pages = (*self.pages, page.id)
        return ResolvedScope(
            effective_scope=self._scope,
            source_group_id=(
                self._scope.group_ids[0] if self._scope.group_ids is not None else None
            ),
            thread_id=self._scope.thread_id,
            shared_group_id=self._scope.shared_group_id,
        )


class _EchoSourceEventSynthesis:
    def __init__(self) -> None:
        self.requests: list[PageMemorySynthesisRequest] = []

    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        self.requests.append(request)
        source_event_ids = tuple(event.id for event in request.source_events)
        return PageMemorySynthesis(
            title="Resolver-authorized rebuild",
            brief="The worker used the resolver-authorized scope.",
            topics=(
                PageMemoryTopic(
                    title="Authorized source",
                    summary="The synthesis input comes from the resolver scope.",
                    source_event_ids=source_event_ids,
                    linked_memory_item_ids=(),
                ),
            ),
            open_questions=(),
            next_steps=(),
            source_event_ids=source_event_ids,
            linked_memory_item_ids=(),
        )
