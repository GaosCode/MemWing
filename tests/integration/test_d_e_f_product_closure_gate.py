from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_knowledge import AgentKnowledgeExplainRequest, AgentKnowledgeGetRequest
from memwing.api.agent_memory import AgentMemoryQuery
from memwing.application.access_service import MemoryAccessService
from memwing.application.decay_service import DecayProcessCommand, DecayService
from memwing.application.decision_card_service import DecisionCardCommand, DecisionCardService
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import MemoryDisplayType, MemoryItem, MemoryRoute, MemoryStatus, SourceEvent
from memwing.core.scope import MemoryScope, ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.lifecycle_transition import LifecycleTransitionRequest


NOW = datetime(2026, 4, 30, tzinfo=UTC)


def test_d_e_f_closure_gate_decay_review_confirm_then_default_recall() -> None:
    async def scenario() -> None:
        store = _store()
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(_source_event())
            await tx.memory_items.upsert(_memory_item())

        lifecycle = LifecycleTransitionService(store)
        decay = DecayService(store, lifecycle)
        access = MemoryAccessService(ScopeResolver(store), store, now=lambda: NOW)

        decay_result = await decay.process_project(
            DecayProcessCommand(
                project_memory_space_id="project_001",
                now=NOW,
                threshold=0.5,
                trace_id="closure_gate:decay",
            )
        )

        assert decay_result.review_candidate_count == 1
        assert store.forgetting_review_candidates[0].memory_id == "memory_001"
        assert store.forgetting_review_candidates[0].status == "pending"
        async with store.transaction() as tx:
            needs_review = await tx.memory_items.get("memory_001")
        assert needs_review is not None
        assert needs_review.status is MemoryStatus.NEEDS_REVIEW

        before_confirm = await access.search(
            AgentMemoryQuery(
                runtime_ref=_runtime_ref(),
                query="OpenClaw plugin memory backend",
                scope=MemoryScope(project_memory_space_id="project_001"),
            )
        )
        assert before_confirm.results == ()

        await lifecycle.transition(
            LifecycleTransitionRequest(
                memory_id="memory_001",
                action=LifecycleAction.CONFIRM,
                actor_id="user_001",
                reason="user confirmed memory remains useful",
                idempotency_key="confirm:memory_001",
                trace_id="closure_gate:confirm",
                now=NOW,
            )
        )

        recall = await access.search(
            AgentMemoryQuery(
                runtime_ref=_runtime_ref(),
                query="OpenClaw plugin memory backend",
                scope=MemoryScope(project_memory_space_id="project_001"),
            )
        )
        detail = await access.get(
            AgentKnowledgeGetRequest(
                runtime_ref=_runtime_ref(),
                memory_id="memory_001",
                include_evidence=True,
                scope=MemoryScope(project_memory_space_id="project_001"),
            )
        )
        explain = await access.explain(
            AgentKnowledgeExplainRequest(
                runtime_ref=_runtime_ref(),
                memory_id="memory_001",
                scope=MemoryScope(project_memory_space_id="project_001"),
            )
        )

        assert tuple(item.id for item in recall.results) == ("memory_001",)
        assert detail.item is not None
        assert detail.item.id == "memory_001"
        assert tuple(item.id for item in detail.evidence) == ("source_001",)
        assert explain.source_event_ids == ("source_001",)
        assert "active" in explain.rationale

    asyncio.run(scenario())


def test_direction_b_decision_change_current_history_explain_and_decision_card() -> None:
    async def scenario() -> None:
        store = _store()
        async with store.transaction() as tx:
            await tx.source_events.insert_if_absent(
                _decision_source_event(
                    "source_decision_old",
                    "The project codename is Apollo.",
                    days_ago=4,
                )
            )
            await tx.source_events.insert_if_absent(
                _decision_source_event(
                    "source_decision_new",
                    "The project codename is Skyline.",
                    days_ago=1,
                )
            )
            await tx.memory_items.upsert(
                _decision_memory_item(
                    "memory_decision_old",
                    "Apollo project codename",
                    "The project codename is Apollo.",
                    "source_decision_old",
                    MemoryStatus.ACTIVE,
                )
            )
            await tx.memory_items.upsert(
                _decision_memory_item(
                    "memory_decision_new",
                    "Skyline project codename",
                    "The project codename is Skyline.",
                    "source_decision_new",
                    MemoryStatus.CANDIDATE,
                )
            )

        lifecycle = LifecycleTransitionService(store)
        await lifecycle.transition(
            LifecycleTransitionRequest(
                memory_id="memory_decision_old",
                action=LifecycleAction.INVALIDATE,
                actor_id="user_001",
                reason="project decision changed",
                idempotency_key="invalidate:memory_decision_old",
                trace_id="direction_b:invalidate_old",
                now=NOW,
            )
        )
        await lifecycle.transition(
            LifecycleTransitionRequest(
                memory_id="memory_decision_new",
                action=LifecycleAction.CONFIRM,
                actor_id="user_001",
                reason="project decision changed",
                idempotency_key="confirm:memory_decision_new",
                trace_id="direction_b:confirm_new",
                now=NOW,
            )
        )

        access = MemoryAccessService(ScopeResolver(store), store, now=lambda: NOW)
        current = await access.search(
            AgentMemoryQuery(
                runtime_ref=_runtime_ref(),
                query="project codename",
                scope=MemoryScope(project_memory_space_id="project_001"),
                mode="current",
            )
        )
        history = await access.search(
            AgentMemoryQuery(
                runtime_ref=_runtime_ref(),
                query="project codename",
                scope=MemoryScope(project_memory_space_id="project_001"),
                mode="history",
            )
        )
        explain_old = await access.explain(
            AgentKnowledgeExplainRequest(
                runtime_ref=_runtime_ref(),
                memory_id="memory_decision_old",
                scope=MemoryScope(project_memory_space_id="project_001"),
            )
        )
        decision_card = await DecisionCardService(store).create_for_memory(
            DecisionCardCommand(
                memory_id="memory_decision_new",
                now=NOW,
                trigger_reason="project_decision_changed",
                trace_id="direction_b:decision_card",
            )
        )

        assert tuple(item.id for item in current.results) == ("memory_decision_new",)
        assert {item.id for item in history.results} == {
            "memory_decision_old",
            "memory_decision_new",
        }
        assert explain_old.source_event_ids == ("source_decision_old",)
        assert "invalid" in explain_old.rationale
        assert decision_card.type == "decision_card"
        assert decision_card.status == "pending"
        assert decision_card.memory_item_ids == ("memory_decision_new",)
        assert decision_card.source_event_ids == ("source_decision_new",)
        assert store.push_candidates == (decision_card,)

    asyncio.run(scenario())


def _store() -> InMemoryDataStore:
    store = InMemoryDataStore()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Demo",
            default_safe_mode_enabled=False,
        )
    )
    store.add_runtime_scope_binding(
        RuntimeScopeBinding(
            runtime="openclaw",
            agent_id="main",
            workspace_id="workspace_001",
            session_key_pattern="session_001",
            project_memory_space_id="project_001",
        )
    )
    return store


def _runtime_ref() -> AgentRuntimeRef:
    return AgentRuntimeRef(
        runtime="openclaw",
        agent_id="main",
        workspace_id="workspace_001",
        session_id="session_001",
    )


def _decision_source_event(source_event_id: str, content: str, *, days_ago: int) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="agent_runtime.message_ingested",
        content=content,
        content_preview=content,
        source_url=None,
        event_time=NOW - timedelta(days=days_ago),
        raw_payload_hash=f"hash:{source_event_id}",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW - timedelta(days=days_ago),
        runtime_event_idempotency_key=f"runtime:{source_event_id}",
    )


def _decision_memory_item(
    memory_id: str,
    title: str,
    content: str,
    source_event_id: str,
    status: MemoryStatus,
) -> MemoryItem:
    activated_at = NOW - timedelta(days=4) if status is MemoryStatus.ACTIVE else None
    return MemoryItem(
        id=memory_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.VECTOR_ONLY,
        display_type=MemoryDisplayType.DECISION,
        title=title,
        content=content,
        summary=None,
        source_event_ids=(source_event_id,),
        primary_source_event_id=source_event_id,
        status=status,
        event_time=NOW,
        valid_from=None,
        valid_to=None,
        original_score=0.9,
        half_life_days=180,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=NOW - timedelta(days=4),
        activated_at=activated_at,
        updated_at=NOW - timedelta(days=4),
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
        source_type="agent_runtime.message_ingested",
        content="The OpenClaw plugin memory backend must support recall.",
        content_preview="The OpenClaw plugin memory backend must support recall.",
        source_url=None,
        event_time=NOW - timedelta(days=10),
        raw_payload_hash="hash:source_001",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW - timedelta(days=10),
        runtime_event_idempotency_key="runtime:source_001",
    )


def _memory_item() -> MemoryItem:
    return MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.VECTOR_ONLY,
        display_type=MemoryDisplayType.NOTE,
        title="OpenClaw plugin memory backend",
        content="OpenClaw plugin memory backend supports default recall after confirmation.",
        summary=None,
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=MemoryStatus.ACTIVE,
        event_time=NOW - timedelta(days=10),
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
        created_at=NOW - timedelta(days=10),
        activated_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(days=10),
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
    )
