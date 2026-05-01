from datetime import UTC, datetime

from memwing.core.models import (
    EvidenceChunk,
    ForgettingReviewCandidate,
    LongTermFilterItem,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryPageVersion,
    MemoryRoute,
    MemoryStatus,
    MemoryVersion,
    PageMemory,
    PageMemorySynthesis,
    PageMemoryTopic,
    PushCandidate,
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
    topic = PageMemoryTopic(
        title="OpenClaw ingest",
        summary="The team is validating OpenClaw ingest before recall.",
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
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
        topics=(topic,),
        open_questions=("How should recall warnings surface?",),
        next_steps=("Run the OpenClaw ingest smoke.",),
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
        topics=page.topics,
        open_questions=page.open_questions,
        next_steps=page.next_steps,
        source_event_ids=page.source_event_ids,
        linked_memory_item_ids=page.linked_memory_item_ids,
        changed_by="system",
        change_reason="initial_rebuild",
        created_at=event_time,
    )

    assert evidence.source_event_id == "source_001"
    assert evidence.invalidated_at is None
    assert working.source_event_id == "source_001"
    assert page.topics == (topic,)
    assert page.open_questions == ("How should recall warnings surface?",)
    assert page.next_steps == ("Run the OpenClaw ingest smoke.",)
    assert page.source_event_ids == ("source_001",)
    assert page.linked_memory_item_ids == ("memory_001",)
    assert version.topics == page.topics
    assert version.version == page.version


def test_page_memory_synthesis_contract_requires_structured_topics() -> None:
    synthesis = PageMemorySynthesis(
        title="Thread mainline",
        brief="The thread is validating memory lanes.",
        topics=(
            PageMemoryTopic(
                title="Persistence contract",
                summary="Derived repositories are available for lane workers.",
                source_event_ids=("source_001",),
                linked_memory_item_ids=("memory_001",),
            ),
        ),
        open_questions=("Which warning belongs in recall?",),
        next_steps=("Wire the page memory worker.",),
        source_event_ids=("source_001",),
        linked_memory_item_ids=("memory_001",),
    )

    assert synthesis.topics[0].title == "Persistence contract"
    assert synthesis.topics[0].source_event_ids == ("source_001",)
    assert synthesis.open_questions == ("Which warning belongs in recall?",)
    assert synthesis.next_steps == ("Wire the page memory worker.",)


def test_push_candidate_contract_preserves_decision_card_lineage() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    candidate = PushCandidate(
        id="push_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        type="decision_card",
        title="Skyline project codename",
        content="The project codename changed to Skyline.",
        memory_item_ids=("memory_001",),
        source_event_ids=("source_001",),
        trigger_reason="project_decision_changed",
        trigger_source="memory_item",
        priority=100,
        expires_at=None,
        status="pending",
        cooldown_key="decision_card:project_001:memory_001",
        created_at=event_time,
        updated_at=event_time,
    )

    assert candidate.type == "decision_card"
    assert candidate.memory_item_ids == ("memory_001",)
    assert candidate.source_event_ids == ("source_001",)


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


def test_forgetting_review_candidate_contract_shape() -> None:
    candidate = ForgettingReviewCandidate(
        id="forgetting_review_001",
        memory_id="memory_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id=None,
        decayed_score=0.42,
        threshold=0.5,
        reason="score_below_threshold",
        status="pending",
        created_at=datetime(2026, 4, 30, tzinfo=UTC),
        updated_at=datetime(2026, 4, 30, tzinfo=UTC),
    )

    assert candidate.memory_id == "memory_001"
    assert candidate.status == "pending"
    assert candidate.decayed_score == 0.42
