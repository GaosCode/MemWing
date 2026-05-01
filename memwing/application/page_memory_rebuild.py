from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

from memwing.core.models import (
    AuditEvent,
    MemoryItem,
    MemoryPageVersion,
    MemoryStatus,
    PageMemory,
    PageMemoryScopeType,
    PageMemorySynthesis,
    SourceEvent,
)
from memwing.core.scope import EffectiveScope
from memwing.ports.page_memory_synthesis import PageMemorySynthesisRequest


DEFAULT_PAGE_MEMORY_SOURCE_EVENT_LIMIT = 200
DEFAULT_PAGE_MEMORY_LINKED_ITEM_LIMIT = 50
NEEDS_REBUILD_REASON = "needs_rebuild"
_PINNED_CURRENT_EXCLUDED_STATUSES = frozenset(
    {
        MemoryStatus.CANDIDATE,
        MemoryStatus.ARCHIVED,
        MemoryStatus.HIDDEN,
        MemoryStatus.INVALID,
        MemoryStatus.REMOVED,
    }
)


class PageMemoryRebuildError(RuntimeError):
    pass


class PageMemorySynthesisValidationError(PageMemoryRebuildError):
    pass


@dataclass(frozen=True, slots=True)
class PageMemoryRebuildCommand:
    scope: EffectiveScope
    scope_type: PageMemoryScopeType
    scope_id: str
    actor_id: str | None
    reason: str
    trace_id: str


@dataclass(frozen=True, slots=True)
class PageMemoryRebuildResult:
    page: PageMemory
    version: MemoryPageVersion
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class PageMemoryRebuildNoOp:
    page: PageMemory
    reason: str


@dataclass(frozen=True, slots=True)
class PageMemoryRebuildPlan:
    command: PageMemoryRebuildCommand
    existing_page: PageMemory | None
    source_events: tuple[SourceEvent, ...]
    linked_memory_items: tuple[MemoryItem, ...]
    rebuild_reason: str

    def synthesis_request(self) -> PageMemorySynthesisRequest:
        return PageMemorySynthesisRequest(
            scope=self.command.scope,
            source_events=self.source_events,
            existing_page=self.existing_page,
            linked_memory_items=self.linked_memory_items,
        )


@dataclass(frozen=True, slots=True)
class PageMemoryRebuildPreview:
    title: str
    brief: str
    source_event_ids: tuple[str, ...]
    linked_memory_item_ids: tuple[str, ...]
    topic_count: int
    open_questions: tuple[str, ...]
    next_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GuardedPageMemorySynthesis:
    plan: PageMemoryRebuildPlan
    synthesis: PageMemorySynthesis

    def preview(self) -> PageMemoryRebuildPreview:
        return PageMemoryRebuildPreview(
            title=self.synthesis.title,
            brief=self.synthesis.brief,
            source_event_ids=self.synthesis.source_event_ids,
            linked_memory_item_ids=self.synthesis.linked_memory_item_ids,
            topic_count=len(self.synthesis.topics),
            open_questions=self.synthesis.open_questions,
            next_steps=self.synthesis.next_steps,
        )


class PageMemoryRebuildPlanner:
    def __init__(
        self,
        *,
        source_event_limit: int = DEFAULT_PAGE_MEMORY_SOURCE_EVENT_LIMIT,
        linked_item_limit: int = DEFAULT_PAGE_MEMORY_LINKED_ITEM_LIMIT,
    ) -> None:
        self._source_event_limit = source_event_limit
        self._linked_item_limit = linked_item_limit

    async def plan(self, tx: object, command: PageMemoryRebuildCommand) -> PageMemoryRebuildPlan:
        _validate_command(command)
        existing_page = await tx.memory_pages.get_by_scope(
            project_memory_space_id=command.scope.project_memory_space_id,
            scope_type=command.scope_type,
            scope_id=command.scope_id,
        )
        source_events = await tx.source_events.list_recent_for_scope(
            scope=command.scope,
            limit=self._source_event_limit,
        )
        if not source_events:
            raise PageMemoryRebuildError("page memory rebuild requires source_events")
        _validate_source_events_not_redacted(source_events)
        linked_memory_items = await tx.memory_items.list_for_scope(
            scope=command.scope,
            limit=self._linked_item_limit,
        )
        return PageMemoryRebuildPlan(
            command=command,
            existing_page=existing_page,
            source_events=source_events,
            linked_memory_items=_current_page_memory_items(linked_memory_items),
            rebuild_reason=command.reason,
        )


class PageMemorySynthesisGuard:
    def validate(
        self,
        *,
        plan: PageMemoryRebuildPlan,
        synthesis: PageMemorySynthesis,
    ) -> GuardedPageMemorySynthesis:
        _validate_synthesis(
            synthesis=synthesis,
            source_events=plan.source_events,
            linked_memory_items=plan.linked_memory_items,
        )
        return GuardedPageMemorySynthesis(plan=plan, synthesis=synthesis)


class PageMemoryCommit:
    async def commit(
        self,
        tx: object,
        *,
        command: PageMemoryRebuildCommand,
        current_page: PageMemory | None,
        guarded: GuardedPageMemorySynthesis,
        now: datetime,
    ) -> PageMemoryRebuildResult:
        page = _page_from_synthesis(
            command=command,
            existing_page=current_page,
            synthesis=guarded.synthesis,
            now=now,
        )
        version = _page_version(page, reason=command.reason, now=now)
        audit_event = _audit_event(
            page=page,
            command=command,
            source_event_ids=guarded.synthesis.source_event_ids,
            now=now,
        )
        persisted_page = await tx.memory_pages.upsert(page)
        persisted_version = await tx.memory_page_versions.record(version)
        persisted_audit_event = await tx.audit_events.record(audit_event)
        return PageMemoryRebuildResult(
            page=persisted_page,
            version=persisted_version,
            audit_event=persisted_audit_event,
        )


def source_event_ids(events: tuple[SourceEvent, ...]) -> tuple[str, ...]:
    return tuple(event.id for event in events)


def current_source_window_changed(
    current_source_events: tuple[SourceEvent, ...],
    plan: PageMemoryRebuildPlan,
) -> bool:
    return source_event_ids(current_source_events) != source_event_ids(plan.source_events)


def _validate_command(command: PageMemoryRebuildCommand) -> None:
    if not command.scope_id.strip():
        raise PageMemoryRebuildError("page memory rebuild requires scope_id")
    if not command.reason.strip():
        raise PageMemoryRebuildError("page memory rebuild requires reason")
    if not command.trace_id.strip():
        raise PageMemoryRebuildError("page memory rebuild requires trace_id")
    if command.scope_type not in ("project", "group", "thread", "meeting"):
        raise PageMemoryRebuildError("page memory rebuild scope_type is not supported")
    _validate_scope_id_matches_scope(command)
    group_id = _scope_group_id(command.scope)
    if command.scope.safe_mode_enabled and group_id is None:
        raise PageMemoryRebuildError("safe_mode requires group_id")


def _validate_scope_id_matches_scope(command: PageMemoryRebuildCommand) -> None:
    if command.scope_type == "project":
        if command.scope.group_ids is not None:
            raise PageMemoryRebuildError("project page memory rebuild requires project scope")
        if command.scope.thread_id is not None:
            raise PageMemoryRebuildError("project page memory rebuild requires project scope")
        if command.scope.shared_group_id is not None:
            raise PageMemoryRebuildError("project page memory rebuild requires project scope")
        expected_scope_id = command.scope.project_memory_space_id
    elif command.scope_type == "group":
        group_id = _scope_group_id(command.scope)
        if group_id is None:
            raise PageMemoryRebuildError("group page memory rebuild requires group scope")
        if command.scope.thread_id is not None:
            raise PageMemoryRebuildError("group page memory rebuild requires group scope")
        if command.scope.shared_group_id is not None:
            raise PageMemoryRebuildError("group page memory rebuild requires group scope")
        expected_scope_id = group_id
    elif command.scope_type == "thread":
        if command.scope.thread_id is None:
            raise PageMemoryRebuildError("thread page memory rebuild requires thread scope")
        expected_scope_id = command.scope.thread_id
    else:
        if command.scope.thread_id is None:
            raise PageMemoryRebuildError("meeting page memory rebuild requires thread scope")
        expected_scope_id = command.scope.thread_id

    if command.scope_id != expected_scope_id:
        raise PageMemoryRebuildError("page memory rebuild scope_id conflicts with EffectiveScope")


def _validate_synthesis(
    *,
    synthesis: PageMemorySynthesis,
    source_events: tuple[SourceEvent, ...],
    linked_memory_items: tuple[MemoryItem, ...],
) -> None:
    if not isinstance(synthesis, PageMemorySynthesis):
        raise PageMemorySynthesisValidationError("synthesis must return PageMemorySynthesis")
    _require_text(synthesis.title, "synthesis title is required")
    _require_text(synthesis.brief, "synthesis brief is required")
    if not synthesis.topics:
        raise PageMemorySynthesisValidationError("synthesis topics are required")
    if not synthesis.source_event_ids:
        raise PageMemorySynthesisValidationError("synthesis source_event_ids are required")

    _validate_source_events_not_redacted(source_events)
    input_source_ids = {event.id for event in source_events}
    linked_item_ids = {item.id for item in linked_memory_items}
    page_source_ids = set(synthesis.source_event_ids)
    page_linked_item_ids = set(synthesis.linked_memory_item_ids)
    _require_known_ids(
        synthesis.source_event_ids,
        input_source_ids,
        "synthesis references unknown source_events",
    )
    _require_known_ids(
        synthesis.linked_memory_item_ids,
        linked_item_ids,
        "synthesis references unknown memory_items",
    )
    for topic in synthesis.topics:
        _require_text(topic.title, "synthesis topic title is required")
        _require_text(topic.summary, "synthesis topic summary is required")
        if not topic.source_event_ids:
            raise PageMemorySynthesisValidationError("synthesis topic source_event_ids are required")
        _require_known_ids(
            topic.source_event_ids,
            input_source_ids,
            "synthesis topic references unknown source_events",
        )
        _require_known_ids(
            topic.source_event_ids,
            page_source_ids,
            "synthesis topic source_event_ids must be covered by page source_event_ids",
        )
        _require_known_ids(
            topic.linked_memory_item_ids,
            linked_item_ids,
            "synthesis topic references unknown memory_items",
        )
        _require_known_ids(
            topic.linked_memory_item_ids,
            page_linked_item_ids,
            "synthesis topic linked_memory_item_ids must be covered by page linked_memory_item_ids",
        )
    for open_question in synthesis.open_questions:
        _require_text(open_question, "synthesis open_questions cannot be blank")
    for next_step in synthesis.next_steps:
        _require_text(next_step, "synthesis next_steps cannot be blank")


def _validate_source_events_not_redacted(source_events: tuple[SourceEvent, ...]) -> None:
    if any(event.purged_at is not None or event.purge_level != "none" for event in source_events):
        raise PageMemorySynthesisValidationError("redacted source_events cannot rebuild page memory")


def _current_page_memory_items(items: tuple[MemoryItem, ...]) -> tuple[MemoryItem, ...]:
    return tuple(item for item in items if _is_current_page_memory_item(item))


def _is_current_page_memory_item(item: MemoryItem) -> bool:
    if item.status == MemoryStatus.ACTIVE:
        return True
    return item.pinned and item.status not in _PINNED_CURRENT_EXCLUDED_STATUSES


def _require_text(value: str, message: str) -> None:
    if not value.strip():
        raise PageMemorySynthesisValidationError(message)


def _require_known_ids(
    ids: tuple[str, ...],
    known_ids: set[str],
    message: str,
) -> None:
    if any(item_id not in known_ids for item_id in ids):
        raise PageMemorySynthesisValidationError(message)


def _page_from_synthesis(
    *,
    command: PageMemoryRebuildCommand,
    existing_page: PageMemory | None,
    synthesis: PageMemorySynthesis,
    now: datetime,
) -> PageMemory:
    page_id = (
        existing_page.id
        if existing_page is not None
        else _stable_id(
            "memory_page",
            command.scope.project_memory_space_id,
            command.scope_type,
            command.scope_id,
        )
    )
    return PageMemory(
        id=page_id,
        project_memory_space_id=command.scope.project_memory_space_id,
        group_id=_scope_group_id(command.scope),
        thread_id=command.scope.thread_id,
        shared_group_id=command.scope.shared_group_id,
        scope_type=command.scope_type,
        scope_id=command.scope_id,
        title=synthesis.title,
        brief=synthesis.brief,
        topics=synthesis.topics,
        open_questions=synthesis.open_questions,
        next_steps=synthesis.next_steps,
        source_event_ids=synthesis.source_event_ids,
        linked_memory_item_ids=synthesis.linked_memory_item_ids,
        version=(existing_page.version + 1 if existing_page is not None else 1),
        needs_rebuild=False,
        created_at=existing_page.created_at if existing_page is not None else now,
        updated_at=now,
    )


def _page_version(
    page: PageMemory,
    *,
    reason: str,
    now: datetime,
) -> MemoryPageVersion:
    return MemoryPageVersion(
        id=_stable_id("memory_page_version", page.id, str(page.version)),
        page_id=page.id,
        version=page.version,
        title=page.title,
        brief=page.brief,
        topics=page.topics,
        open_questions=page.open_questions,
        next_steps=page.next_steps,
        source_event_ids=page.source_event_ids,
        linked_memory_item_ids=page.linked_memory_item_ids,
        changed_by="system",
        change_reason=reason,
        created_at=now,
    )


def _audit_event(
    *,
    page: PageMemory,
    command: PageMemoryRebuildCommand,
    source_event_ids: tuple[str, ...],
    now: datetime,
) -> AuditEvent:
    return AuditEvent(
        id=_stable_id("audit", command.trace_id, page.id, str(page.version)),
        trace_id=command.trace_id,
        entity_type="memory_page",
        entity_id=page.id,
        stage="page_memory.rebuilt",
        input_ref="source_events",
        output_ref=page.id,
        decision="rebuilt",
        reason_code=command.reason,
        reason_text=command.reason,
        source_event_ids=source_event_ids,
        latency_ms=None,
        created_at=now,
        actor_id=command.actor_id,
    )


def _scope_group_id(scope: EffectiveScope) -> str | None:
    if scope.group_ids is None:
        return None
    if len(scope.group_ids) != 1:
        raise PageMemoryRebuildError("page memory rebuild requires at most one group_id")
    return scope.group_ids[0]


def _stable_id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))
