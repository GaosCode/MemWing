from __future__ import annotations

from memwing.core.models import MemoryItem, PageMemory, PushCandidate, SourceEvent
from memwing.core.scope import EffectiveScope, effective_scope_matches


def scope_values_visible_in_scope(
    *,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
    effective_scope: EffectiveScope,
) -> bool:
    return effective_scope_matches(
        group_id=group_id,
        thread_id=thread_id,
        shared_group_id=shared_group_id,
        scope=effective_scope,
    )


def source_event_visible_in_scope(
    source_event: SourceEvent,
    effective_scope: EffectiveScope,
) -> bool:
    return (
        source_event.project_memory_space_id == effective_scope.project_memory_space_id
        and scope_values_visible_in_scope(
            group_id=source_event.group_id,
            thread_id=source_event.thread_id,
            shared_group_id=source_event.shared_group_id,
            effective_scope=effective_scope,
        )
    )


def memory_item_visible_in_scope(
    memory_item: MemoryItem,
    effective_scope: EffectiveScope,
) -> bool:
    return (
        memory_item.project_memory_space_id == effective_scope.project_memory_space_id
        and scope_values_visible_in_scope(
            group_id=memory_item.group_id,
            thread_id=memory_item.thread_id,
            shared_group_id=memory_item.shared_group_id,
            effective_scope=effective_scope,
        )
    )


def page_memory_visible_in_scope(
    page_memory: PageMemory,
    effective_scope: EffectiveScope,
) -> bool:
    return (
        page_memory.project_memory_space_id == effective_scope.project_memory_space_id
        and scope_values_visible_in_scope(
            group_id=page_memory.group_id,
            thread_id=page_memory.thread_id,
            shared_group_id=page_memory.shared_group_id,
            effective_scope=effective_scope,
        )
    )


def push_candidate_visible_in_scope(
    push_candidate: PushCandidate,
    effective_scope: EffectiveScope,
) -> bool:
    return (
        push_candidate.project_memory_space_id == effective_scope.project_memory_space_id
        and scope_values_visible_in_scope(
            group_id=push_candidate.group_id,
            thread_id=push_candidate.thread_id,
            shared_group_id=push_candidate.shared_group_id,
            effective_scope=effective_scope,
        )
    )
