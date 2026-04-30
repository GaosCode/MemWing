from datetime import UTC, datetime

from memwing.api.schemas import (
    AgentContextRequest,
    AgentContextResult,
    AgentMemoryResultItem,
    AgentMemorySearchResult,
    AgentRuntimeEvent,
    AgentRuntimeRef,
    PlatformEvent,
    PlatformRawEvent,
    PlatformRawRequest,
    PlatformRef,
    PlatformSendResult,
    PushCandidate,
)
from memwing.core.models import (
    GraphBackendCapabilities,
    GraphFact,
    GraphWriteJob,
    GraphWriteResult,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    SourceEvent,
)
from memwing.core.scope import MemoryScope


def test_agent_runtime_ref_event_and_context_are_locked_contracts() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    runtime_ref = AgentRuntimeRef(
        runtime="openclaw",
        agent_id="agent_001",
        workspace_id="workspace_001",
        session_id="session_001",
    )
    scope = MemoryScope(project_memory_space_id="project_001", group_id="group_001")
    event = AgentRuntimeEvent(
        runtime_ref=runtime_ref,
        run_id="run_001",
        message_id="message_001",
        tool_call_id=None,
        hook_name="afterTurn",
        sequence=1,
        idempotency_key="openclaw:agent_001:session_001:run_001:afterTurn:message_001",
        event_type="turn_completed",
        scope=scope,
        content="Decision captured.",
        payload={"turn": "complete"},
        event_time=event_time,
    )
    request = AgentContextRequest(
        runtime_ref=runtime_ref,
        scope=scope,
        prompt="What changed?",
        messages=({"role": "user", "content": "What changed?"},),
        token_budget=2048,
        available_tools=("memwing_search_memory",),
    )
    result = AgentContextResult(
        messages=None,
        system_prompt_addition="Use the current project memory.",
        context_blocks=({"type": "memory", "content": "Decision captured."},),
        estimated_tokens=42,
        trace_id="trace_001",
    )

    assert event.runtime_ref is runtime_ref
    assert event.scope is scope
    assert event.event_type == "turn_completed"
    assert request.messages == ({"role": "user", "content": "What changed?"},)
    assert result.context_blocks == ({"type": "memory", "content": "Decision captured."},)


def test_agent_memory_search_result_uses_neutral_result_items() -> None:
    item = AgentMemoryResultItem(
        id="memory_001",
        text="Demo scope is limited to Feishu and OpenClaw.",
        score=0.91,
        source="memory_item",
        source_event_ids=("source_001",),
        memory_item_ids=("memory_001",),
        valid_from=None,
        valid_to=None,
        metadata={"route": "manual"},
    )
    result = AgentMemorySearchResult(
        contexts=("Demo context",),
        results=(item,),
        next_cursor=None,
        trace_id="trace_001",
    )

    assert result.results == (item,)
    assert result.results[0].source == "memory_item"
    assert result.contexts == ("Demo context",)


def test_platform_event_uses_platform_neutral_reference() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    event = PlatformEvent(
        platform_ref=PlatformRef(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id="thread_001",
            message_id="message_001",
        ),
        project_memory_space_id="project_001",
        group_id="feishu_group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content="Ship the demo scope.",
        source_url=None,
        event_time=event_time,
        raw_payload={"message_id": "message_001"},
    )

    assert event.platform_ref.platform == "feishu"
    assert event.content == "Ship the demo scope."
    assert event.event_time is event_time


def test_platform_raw_and_send_contracts_cover_webhook_boundary() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    raw_request = PlatformRawRequest(
        platform="feishu",
        headers={"x-lark-request-timestamp": "1714233600"},
        body=b'{"challenge":"abc"}',
        received_at=event_time,
        raw_payload_hash="hash_001",
    )
    raw_event = PlatformRawEvent(
        platform_ref=PlatformRef(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id=None,
            message_id="message_001",
        ),
        raw_request=raw_request,
        event_payload={"type": "message"},
        is_challenge=False,
    )
    candidate = PushCandidate(
        id="push_001",
        platform_ref=raw_event.platform_ref,
        content="Review this memory.",
        trace_id="trace_001",
    )
    result = PlatformSendResult(
        candidate_id="push_001",
        delivered=True,
        trace_id="trace_001",
        provider_message_id="message_002",
    )

    assert raw_request.body == b'{"challenge":"abc"}'
    assert raw_event.raw_request is raw_request
    assert candidate.platform_ref is raw_event.platform_ref
    assert result.provider_message_id == "message_002"


def test_graph_backend_contract_uses_neutral_fact_types() -> None:
    capabilities = GraphBackendCapabilities(
        supports_temporal_facts=True,
        supports_fact_invalidation=True,
        supports_episode_provenance=True,
        supports_current_search=True,
        supports_history_search=True,
        supports_source_redaction_marker=True,
    )
    fact = GraphFact(
        backend="graphiti",
        fact_id="fact_001",
        fact_text="Demo scope is limited to Feishu and OpenClaw.",
        source_event_ids=("source_001",),
        valid_from=None,
        valid_to=None,
        invalidated_at=None,
        confidence=0.91,
        metadata={},
    )
    result = GraphWriteResult(
        backend="graphiti",
        facts=(fact,),
        invalidated_facts=(),
        backend_episode_refs=("episode_001",),
        backend_fact_refs=("fact_001",),
    )

    assert capabilities.supports_current_search is True
    assert result.facts == (fact,)
    assert result.backend_fact_refs == ("fact_001",)


def test_graph_write_job_contract_carries_worker_claim_fields() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    job = GraphWriteJob(
        id="graph_job_001",
        backend="graphiti",
        project_memory_space_id="project_001",
        thread_id="thread_001",
        saga_id=None,
        memory_id="memory_001",
        source_event_ids=("source_001",),
        route=MemoryRoute.GRAPH,
        status="pending",
        idempotency_key="graph:memory_001",
        attempts=0,
        max_attempts=3,
        priority=10,
        next_run_at=event_time,
        dead_letter_reason=None,
        last_error=None,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        created_at=event_time,
        updated_at=event_time,
    )

    assert job.route is MemoryRoute.GRAPH
    assert job.memory_id == "memory_001"
    assert job.idempotency_key == "graph:memory_001"
    assert job.max_attempts == 3
    assert job.lock_expires_at is None


def test_source_event_and_memory_item_are_core_neutral_contracts() -> None:
    event_time = datetime(2026, 4, 28, tzinfo=UTC)
    source_event = SourceEvent(
        id="source_001",
        project_memory_space_id="project_001",
        group_id="feishu_group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content="Demo scope is limited to Feishu and OpenClaw.",
        content_preview="Demo scope is limited",
        source_url=None,
        event_time=event_time,
        raw_payload_hash="hash_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=event_time,
        runtime_event_idempotency_key=None,
    )
    memory_item = MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id="feishu_group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.MANUAL,
        display_type=MemoryDisplayType.DECISION,
        title="Demo scope",
        content="Demo scope is limited to Feishu and OpenClaw.",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.CANDIDATE,
        event_time=event_time,
        valid_from=None,
        valid_to=None,
        original_score=0.8,
        half_life_days=30,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=event_time,
        activated_at=None,
        updated_at=event_time,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )

    assert source_event.purge_level == "none"
    assert source_event.graph_backend_raw_retained is False
    assert memory_item.route is MemoryRoute.MANUAL
    assert memory_item.status is MemoryStatus.CANDIDATE
    assert memory_item.lifecycle_revision == 0
    assert memory_item.source_event_ids == ("source_001",)
    assert memory_item.updated_at is event_time
