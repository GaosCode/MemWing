import asyncio

from memwing.application.page_memory_service import PageMemoryRebuildCommand, PageMemoryService
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from tests.integration.test_page_memory_worker import (
    _effective_scope,
    _FakePageMemorySynthesis,
    _seed_source_events,
    _source_event,
    _synthesis,
)


def test_preview_and_manual_rebuild_share_guarded_synthesis_without_preview_commit() -> None:
    store = InMemoryDataStore()
    _seed_source_events(
        store,
        _source_event("source_001", "Previewed content should commit unchanged."),
    )
    synthesis = _FakePageMemorySynthesis(
        _synthesis(
            title="Guarded preview",
            brief="The preview is the same guarded synthesis that commit uses.",
            topic_title="Preview",
            topic_summary="Preview does not write until rebuild commits.",
        )
    )
    service = PageMemoryService(store, synthesis)
    command = PageMemoryRebuildCommand(
        scope=_effective_scope(),
        scope_type="thread",
        scope_id="thread_001",
        actor_id="user_001",
        reason="manual_rebuild",
        trace_id="trace_preview_rebuild",
    )

    async def scenario() -> None:
        preview = await service.preview_rebuild(command)
        assert preview.title == "Guarded preview"
        async with store.transaction() as tx:
            assert tx.state.memory_pages == {}
        assert store.audit_events == ()

        result = await service.rebuild(command)

        assert result.page.title == preview.title
        assert result.page.source_event_ids == preview.source_event_ids
        assert result.version.title == preview.title
        assert result.audit_event.stage == "page_memory.rebuilt"

    asyncio.run(scenario())
