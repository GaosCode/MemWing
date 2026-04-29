from datetime import UTC, datetime

from memwing.core.models import (
    EvidenceChunk,
    LongTermFilterItem,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryPageVersion,
    MemoryRoute,
    MemoryStatus,
    MemoryVersion,
    PageMemory,
    WorkingMemoryEntry,
)


def test_lane_d_derived_memory_contracts_preserve_source_event_authority() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    evidence = EvidenceChunk(
        id="chunk_001",
        source_event_id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        chunk_text="OpenClaw remains the CLI integration.",
        chunk_index=0,
        embedding_model="text-embedding-3-small",
        embedding_ref="embedding_001",
        embedding_vector=None,
        invalidated_at=None,
        created_at=event_time,
    )
    working = WorkingMemoryEntry(
        id="wm_001",
        source_event_id="source_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        content="OpenClaw remains the CLI integration.",
        token_count=8,
        sequence=12,
        flushed_at=None,
        created_at=event_time,
    )
    page = PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="OpenClaw integration",
        brief="The project is validating OpenClaw ingest before recall.",
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
        version=1,
        needs_rebuild=False,
        created_at=event_time,
        updated_at=event_time,
    )
    version = MemoryPageVersion(
        id="page_version_001",
        page_id="page_001",
        version=1,
        title=page.title,
        brief=page.brief,
        source_event_ids=page.source_event_ids,
        linked_memory_item_ids=page.linked_memory_item_ids,
        changed_by="system",
        change_reason="initial_rebuild",
        created_at=event_time,
    )

    assert evidence.source_event_id == "source_001"
    assert evidence.invalidated_at is None
    assert working.source_event_id == "source_001"
    assert page.source_event_ids == ("source_001",)
    assert page.linked_memory_item_ids == ("memory_001",)
    assert version.version == page.version


def test_lane_e_graph_link_contract_is_backend_neutral() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    link = MemoryGraphLink(
        id="graph_link_001",
        backend="graphiti",
        memory_id="memory_001",
        source_event_id="source_001",
        project_memory_space_id="project_001",
        backend_space_id="project_001",
        backend_object_type="entity_edge",
        backend_object_id="edge_001",
        link_type="fact",
        created_at=event_time,
    )

    assert link.backend == "graphiti"
    assert link.backend_object_type == "entity_edge"
    assert link.memory_id == "memory_001"


def test_lane_f_filter_and_version_contracts_do_not_bypass_lifecycle() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    candidate = LongTermFilterItem(
        title="Demo scope",
        content="Demo scope remains Feishu plus OpenClaw.",
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        original_score=0.82,
        half_life_days=30,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        reason="explicit project decision",
        confidence=0.91,
        event_time=event_time,
        valid_from=None,
        valid_to=None,
    )
    version = MemoryVersion(
        id="memory_version_001",
        memory_id="memory_001",
        version=1,
        title=candidate.title,
        content=candidate.content,
        summary=None,
        status=MemoryStatus.CANDIDATE,
        source_event_ids=candidate.source_event_ids,
        changed_by="system",
        change_reason="long_term_filter_candidate",
        created_at=event_time,
    )

    assert candidate.route is MemoryRoute.GRAPH
    assert candidate.display_type is MemoryDisplayType.DECISION
    assert candidate.source_event_ids == ("source_001",)
    assert version.status is MemoryStatus.CANDIDATE
