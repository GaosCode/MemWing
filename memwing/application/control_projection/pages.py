from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from memwing.core.models import MemoryPageVersion, PageMemory, PageMemoryTopic, SourceEvent


@dataclass(frozen=True, slots=True)
class ControlPageTopicProjection:
    title: str
    summary: str
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ControlPageProjection:
    id: str
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None
    scope_type: str
    scope_id: str
    title: str
    brief: str
    topics: tuple[ControlPageTopicProjection, ...]
    open_questions: tuple[str, ...]
    next_steps: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]
    version: int
    needs_rebuild: bool
    graph_backend_raw_retained: bool
    warning_count: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ControlPageListProjection:
    items: tuple[ControlPageProjection, ...]
    next_cursor: str | None
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlPageDetailProjection:
    page: ControlPageProjection
    versions: tuple["ControlPageVersionProjection", ...]
    audit_refs: tuple[str, ...]
    trace_id: str


@dataclass(frozen=True, slots=True)
class ControlPageVersionProjection:
    id: str
    page_id: str
    version: int
    title: str
    brief: str
    topics: tuple[ControlPageTopicProjection, ...]
    open_questions: tuple[str, ...]
    next_steps: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]
    changed_by: str
    change_reason: str
    created_at: datetime


def project_page(
    page: PageMemory,
    *,
    source_events: tuple[SourceEvent, ...],
) -> ControlPageProjection:
    graph_backend_raw_retained = any(event.graph_backend_raw_retained for event in source_events)
    source_redacted = any(event.purged_at is not None or event.purge_level != "none" for event in source_events)
    warning_count = int(page.needs_rebuild) + int(source_redacted) + int(graph_backend_raw_retained)
    return ControlPageProjection(
        id=page.id,
        project_memory_space_id=page.project_memory_space_id,
        group_id=page.group_id,
        thread_id=page.thread_id,
        shared_group_id=page.shared_group_id,
        scope_type=page.scope_type,
        scope_id=page.scope_id,
        title=page.title,
        brief=page.brief,
        topics=tuple(project_page_topic(topic) for topic in page.topics),
        open_questions=page.open_questions,
        next_steps=page.next_steps,
        source_event_ids=page.source_event_ids,
        linked_memory_item_ids=page.linked_memory_item_ids,
        version=page.version,
        needs_rebuild=page.needs_rebuild,
        graph_backend_raw_retained=graph_backend_raw_retained,
        warning_count=warning_count,
        updated_at=page.updated_at,
    )


def project_page_topic(topic: PageMemoryTopic) -> ControlPageTopicProjection:
    return ControlPageTopicProjection(
        title=topic.title,
        summary=topic.summary,
        source_event_ids=topic.source_event_ids,
        linked_memory_item_ids=topic.linked_memory_item_ids,
    )


def project_page_version(version: MemoryPageVersion) -> ControlPageVersionProjection:
    return ControlPageVersionProjection(
        id=version.id,
        page_id=version.page_id,
        version=version.version,
        title=version.title,
        brief=version.brief,
        topics=tuple(project_page_topic(topic) for topic in version.topics),
        open_questions=version.open_questions,
        next_steps=version.next_steps,
        source_event_ids=version.source_event_ids,
        linked_memory_item_ids=version.linked_memory_item_ids,
        changed_by=version.changed_by,
        change_reason=version.change_reason,
        created_at=version.created_at,
    )
