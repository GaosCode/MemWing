from datetime import UTC, datetime
from types import TracebackType

from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import (
    AuditEvent,
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    MemoryVersion,
)
from memwing.ports.lifecycle_transition import LifecycleTransitionRequest


CREATED_AT = datetime(2026, 4, 28, 8, 0, tzinfo=UTC)
NOW = datetime(2026, 4, 28, 9, 30, tzinfo=UTC)


def lifecycle_request(
    *,
    action: LifecycleAction,
    idempotency_key: str,
    reason: str = "Approve reviewed decision",
    now: datetime = NOW,
) -> LifecycleTransitionRequest:
    return LifecycleTransitionRequest(
        memory_id="memory_001",
        action=action,
        actor_id="user_001",
        reason=reason,
        idempotency_key=idempotency_key,
        trace_id="trace_001",
        now=now,
    )


def memory_item(
    *,
    status: MemoryStatus,
    pinned: bool = False,
    updated_at: datetime = CREATED_AT,
    lifecycle_revision: int = 0,
) -> MemoryItem:
    return MemoryItem(
        id="memory_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        route=MemoryRoute.GRAPH,
        display_type=MemoryDisplayType.DECISION,
        title="Launch decision",
        content="The launch stays scoped to OpenClaw and Feishu.",
        summary="Launch scope",
        source_event_ids=("source_001",),
        primary_source_event_id="source_001",
        status=status,
        event_time=CREATED_AT,
        valid_from=None,
        valid_to=None,
        original_score=0.82,
        half_life_days=30,
        last_reviewed_at=None,
        last_confirmed_at=None,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=pinned,
        created_by="system",
        created_at=CREATED_AT,
        activated_at=None,
        updated_at=updated_at,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
        lifecycle_revision=lifecycle_revision,
    )


class TrackingUnitOfWork:
    def __init__(self, memory: MemoryItem) -> None:
        self.audit_events = TrackingAuditEventRepository()
        self.memory_items = TrackingMemoryItemRepository(memory)
        self.memory_versions = TrackingMemoryVersionRepository()

    def transaction(self) -> "TrackingUnitOfWork":
        return self

    async def __aenter__(self) -> "TrackingUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class TrackingAuditEventRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> AuditEvent:
        self.events.append(event)
        return event

    async def get_by_idempotency_key(
        self,
        *,
        entity_type: str,
        entity_id: str,
        idempotency_key: str,
    ) -> AuditEvent | None:
        for event in self.events:
            if (
                event.entity_type == entity_type
                and event.entity_id == entity_id
                and event.idempotency_key == idempotency_key
            ):
                return event
        return None


class TrackingMemoryItemRepository:
    def __init__(self, memory: MemoryItem) -> None:
        self.memory = memory
        self.get_calls: list[str] = []
        self.get_for_update_calls: list[str] = []

    async def upsert(self, item: MemoryItem) -> MemoryItem:
        self.memory = item
        return item

    async def get(self, memory_id: str) -> MemoryItem | None:
        self.get_calls.append(memory_id)
        return self.memory if self.memory.id == memory_id else None

    async def get_for_update(self, memory_id: str) -> MemoryItem | None:
        self.get_for_update_calls.append(memory_id)
        return self.memory if self.memory.id == memory_id else None


class TrackingMemoryVersionRepository:
    def __init__(self) -> None:
        self.versions: list[MemoryVersion] = []

    async def record(self, version: MemoryVersion) -> MemoryVersion:
        self.versions.append(version)
        return version

    async def get_latest(self, memory_id: str) -> MemoryVersion | None:
        versions = [version for version in self.versions if version.memory_id == memory_id]
        versions.sort(key=lambda version: version.version, reverse=True)
        return versions[0] if versions else None
