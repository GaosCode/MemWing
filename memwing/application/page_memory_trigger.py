from __future__ import annotations

from dataclasses import dataclass

from memwing.core.models import PageMemoryScopeType, SourceEvent
from memwing.core.scope import EffectiveScope


@dataclass(frozen=True, slots=True)
class PageMemoryTriggerTarget:
    scope: EffectiveScope
    scope_type: PageMemoryScopeType
    scope_id: str

    @property
    def aggregate_key(self) -> str:
        return page_memory_trigger_key(
            self.scope.project_memory_space_id,
            scope_type=self.scope_type,
            scope_id=self.scope_id,
        )


def page_memory_target_from_source_event(source_event: SourceEvent) -> PageMemoryTriggerTarget:
    if source_event.thread_id is not None:
        scope_type: PageMemoryScopeType = "thread"
        scope_id = source_event.thread_id
    elif source_event.group_id is not None:
        scope_type = "group"
        scope_id = source_event.group_id
    else:
        scope_type = "project"
        scope_id = source_event.project_memory_space_id

    return PageMemoryTriggerTarget(
        scope=EffectiveScope(
            project_memory_space_id=source_event.project_memory_space_id,
            group_ids=(source_event.group_id,) if source_event.group_id is not None else None,
            thread_id=source_event.thread_id,
            shared_group_id=source_event.shared_group_id,
            safe_mode_enabled=source_event.group_id is not None,
            cross_group_allowed=source_event.group_id is None,
        ),
        scope_type=scope_type,
        scope_id=scope_id,
    )


def page_memory_trigger_key_for_scope(scope: EffectiveScope) -> str:
    if scope.thread_id is not None:
        scope_type: PageMemoryScopeType = "thread"
        scope_id = scope.thread_id
    elif scope.group_ids and len(scope.group_ids) == 1:
        scope_type = "group"
        scope_id = scope.group_ids[0]
    else:
        scope_type = "project"
        scope_id = scope.project_memory_space_id
    return page_memory_trigger_key(
        scope.project_memory_space_id,
        scope_type=scope_type,
        scope_id=scope_id,
    )


def page_memory_trigger_key(
    project_memory_space_id: str,
    *,
    scope_type: PageMemoryScopeType,
    scope_id: str,
) -> str:
    return ":".join(("page_memory", project_memory_space_id, scope_type, scope_id))
