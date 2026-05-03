import asyncio
from datetime import UTC, datetime, timedelta

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_memory import AgentMemoryQuery
from memwing.application.access_service import MemoryAccessService
from memwing.application.gateway_service import MemoryGateway
from memwing.application.long_term_filter_service import LongTermFilterService
from memwing.application.page_memory_service import PageMemoryService
from memwing.application.remember_event_command import ActorRef, RememberEventCommand, SourceRef
from memwing.application.scope_resolver import ResolvedScope, ScopeResolver
from memwing.core.models import (
    LongTermFilterItem,
    MemoryDisplayType,
    MemoryRoute,
    PageMemory,
    PageMemorySynthesis,
    PageMemoryTopic,
)
from memwing.core.pipeline_readiness import PipelineReadinessCommand, PipelineReadinessProfile
from memwing.core.scope import EffectiveScope, MemoryScope, ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.llm_filter import LongTermFilterRequest
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest
from memwing.application.pipeline_readiness_service import PipelineReadinessService
from memwing.workers.derived_outbox_worker import DerivedOutboxWorker
from memwing.workers.page_memory_worker import PageMemoryWorker
from memwing.workers.runner import MemWingWorkerRunner


NOW = datetime(2026, 5, 3, 9, tzinfo=UTC)


def test_memory_pipeline_runtime_smoke_derives_page_memory_and_readiness() -> None:
    async def run() -> None:
        store = InMemoryDataStore()
        store.add_project_memory_space(
            ProjectMemorySpace(
                id="project_001",
                name="Project",
                default_safe_mode_enabled=False,
            )
        )
        store.add_runtime_scope_binding(
            RuntimeScopeBinding(
                runtime="openclaw",
                agent_id="agent_001",
                workspace_id="workspace_001",
                session_key_pattern="session_001",
                project_memory_space_id="project_001",
            )
        )
        scope_resolver = ScopeResolver(store)
        gateway = MemoryGateway(store, scope_resolver)
        source_event_ids: list[str] = []
        for index in range(1, 9):
            result = await gateway.remember_event(
                RememberEventCommand(
                    source_ref=SourceRef(
                        kind="agent_runtime",
                        runtime_ref=AgentRuntimeRef(
                            runtime="openclaw",
                            agent_id="agent_001",
                            workspace_id="workspace_001",
                            session_id="session_001",
                        ),
                        run_id="run_001",
                        message_id=f"message_{index:03d}",
                        hook_name="ingest",
                        event_type="message",
                    ),
                    scope_hint=MemoryScope(
                        project_memory_space_id="project_001",
                        group_id="group_001",
                        thread_id="thread_001",
                    ),
                    author=ActorRef(id="user_001", name="Ada"),
                    source_type="agent_runtime.message",
                    content=f"Page Memory smoke event {index} keeps the mainline recallable.",
                    source_url=None,
                    event_time=NOW + timedelta(minutes=index),
                    idempotency_key=f"smoke:{index}",
                    payload_for_dedupe_hash={"message_id": f"message_{index:03d}"},
                    adapter_metadata={},
                )
            )
            source_event_ids.append(result.source_event_id)

        page_memory_worker = PageMemoryWorker(
            store,
            PageMemoryService(store, _EchoPageMemorySynthesis()),
            scope_resolver=_UnusedPageMemoryScopeResolver(),
        )
        runner = MemWingWorkerRunner(
            derived_outbox_worker=DerivedOutboxWorker(
                store,
                evidence_index=None,
                long_term_filter=LongTermFilterService(store, _OneItemLongTermFilter()),
                page_memory_worker=page_memory_worker,
                worker_id="smoke_pipeline",
            ),
            graph_write_worker=None,
        )
        await runner.run_once(now=NOW + timedelta(minutes=20), outbox_limit=100)

        readiness_service = PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
            poll_interval_seconds=0,
        )
        scope = MemoryScope(
            project_memory_space_id="project_001",
            group_id="group_001",
            thread_id="thread_001",
        )
        effective_scope = EffectiveScope(
            project_memory_space_id="project_001",
            group_ids=("group_001",),
            thread_id="thread_001",
            shared_group_id=None,
            safe_mode_enabled=True,
            cross_group_allowed=False,
        )
        readiness = await readiness_service.await_ready(
            PipelineReadinessCommand(
                source_event_ids=tuple(source_event_ids),
                scope=effective_scope,
                profile=PipelineReadinessProfile.WRITE_EVALUATE,
            ),
            timeout_seconds=0,
        )
        access = MemoryAccessService(scope_resolver, store, now=lambda: NOW + timedelta(minutes=30))
        recall = await access.search(
            AgentMemoryQuery(
                runtime_ref=AgentRuntimeRef(
                    runtime="openclaw",
                    agent_id="agent_001",
                    workspace_id="workspace_001",
                    session_id="session_001",
                ),
                query="Page Memory smoke",
                scope=scope,
                mode="current",
                limit=10,
            )
        )

        async with store.transaction() as tx:
            working_count = await tx.working_memory_entries.count_by_source_events(
                project_memory_space_id="project_001",
                source_event_ids=tuple(source_event_ids),
            )
            page = await tx.memory_pages.get_by_scope(
                project_memory_space_id="project_001",
                scope_type="thread",
                scope_id="thread_001",
            )

        assert readiness.ready is True
        assert readiness.derived["working_memory"].count == 8
        assert readiness.derived["page_memory"].count == 1
        assert readiness.derived["memory_items"].count == 1
        assert "evidence_disabled" in readiness.warnings
        assert "graph_disabled" in readiness.warnings
        assert working_count == 8
        assert page is not None
        assert any(item.source == "page_memory" for item in recall.results)

    asyncio.run(run())


class _EchoPageMemorySynthesis:
    async def synthesize(
        self,
        request: PageMemorySynthesisRequest,
    ) -> PageMemorySynthesis:
        source_event_ids = tuple(event.id for event in request.source_events)
        return PageMemorySynthesis(
            title="Page Memory smoke",
            brief="Page Memory smoke can be recalled after pipeline processing.",
            topics=(
                PageMemoryTopic(
                    title="Pipeline smoke",
                    summary="The runtime pipeline derives Page Memory from Source Events.",
                    source_event_ids=source_event_ids,
                    linked_memory_item_ids=(),
                ),
            ),
            open_questions=(),
            next_steps=(),
            source_event_ids=source_event_ids,
            linked_memory_item_ids=(),
        )


class _OneItemLongTermFilter:
    async def filter_events(
        self,
        request: LongTermFilterRequest,
    ) -> tuple[LongTermFilterItem, ...]:
        source_event_ids = tuple(event.id for event in request.source_events)
        return (
            LongTermFilterItem(
                title="Page Memory smoke durable item",
                content="Page Memory smoke durable memory item exists.",
                route=MemoryRoute.MANUAL,
                display_type=MemoryDisplayType.NOTE,
                original_score=0.8,
                half_life_days=30,
                source_event_ids=source_event_ids,
                primary_source_event_id=source_event_ids[0],
                reason="Smoke test durable item.",
                confidence=0.9,
                event_time=NOW,
                valid_from=NOW,
                valid_to=None,
            ),
        )


class _UnusedPageMemoryScopeResolver:
    async def resolve_page_memory_rebuild(self, page: PageMemory) -> ResolvedScope:
        raise AssertionError("source-event triggers should not resolve scope from existing pages")
