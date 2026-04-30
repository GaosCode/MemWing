import asyncio
from datetime import UTC, datetime
from types import TracebackType

import pytest

from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.errors import DomainRuleViolation
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import (
    MemoryDisplayType,
    MemoryItem,
    MemoryRoute,
    MemoryStatus,
    MemoryVersion,
    AuditEvent,
)
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.ports.lifecycle_transition import LifecycleTransitionRequest


CREATED_AT = datetime(2026, 4, 28, 8, 0, tzinfo=UTC)
NOW = datetime(2026, 4, 28, 9, 30, tzinfo=UTC)


def test_candidate_approve_activates_memory_and_records_version_and_audit() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item(status=MemoryStatus.CANDIDATE))

        result = await service.transition(
            _request(
                action=LifecycleAction.APPROVE,
                idempotency_key="lifecycle:memory_001:approve",
            )
        )

        assert result.previous_status is MemoryStatus.CANDIDATE
        assert result.memory_item.status is MemoryStatus.ACTIVE
        assert result.memory_item.lifecycle_revision == 1
        assert result.memory_item.activated_at == NOW
        assert result.memory_item.updated_at == NOW
        assert result.audit_event.stage == "lifecycle_transition.succeeded"
        assert result.audit_event.input_ref == "candidate"
        assert result.audit_event.output_ref == "active"
        assert result.audit_event.decision == "approve"
        assert result.audit_event.action_ref == "approve"
        assert result.audit_event.lifecycle_revision == 1
        assert result.audit_event.reason_text == "Approve reviewed decision"
        assert result.audit_event.idempotency_key == "lifecycle:memory_001:approve"

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version = await tx.memory_versions.get_latest("memory_001")
            audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="memory_item",
                entity_id="memory_001",
                idempotency_key="lifecycle:memory_001:approve",
            )

        assert memory == result.memory_item
        assert latest_version is not None
        assert latest_version.memory_id == "memory_001"
        assert latest_version.version == 1
        assert latest_version.status is MemoryStatus.ACTIVE
        assert latest_version.changed_by == "user"
        assert latest_version.change_reason == "Approve reviewed decision"
        assert audit == result.audit_event

    asyncio.run(scenario())


def test_pin_and_unpin_keep_status_and_do_not_record_memory_versions() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item(status=MemoryStatus.ACTIVE))

        pinned = await service.transition(
            _request(
                action=LifecycleAction.PIN,
                idempotency_key="lifecycle:memory_001:pin",
                reason="Pin high value decision",
            )
        )
        unpinned = await service.transition(
            _request(
                action=LifecycleAction.UNPIN,
                idempotency_key="lifecycle:memory_001:unpin",
                reason="Unpin reviewed decision",
            )
        )

        assert pinned.previous_status is MemoryStatus.ACTIVE
        assert pinned.memory_item.status is MemoryStatus.ACTIVE
        assert pinned.memory_item.pinned is True
        assert pinned.memory_item.lifecycle_revision == 1
        assert pinned.memory_item.updated_at == NOW
        assert pinned.audit_event.output_ref == "pinned:true"
        assert pinned.audit_event.action_ref == "pin"
        assert pinned.audit_event.lifecycle_revision == 1

        assert unpinned.previous_status is MemoryStatus.ACTIVE
        assert unpinned.memory_item.status is MemoryStatus.ACTIVE
        assert unpinned.memory_item.pinned is False
        assert unpinned.memory_item.lifecycle_revision == 2
        assert unpinned.memory_item.updated_at == NOW
        assert unpinned.audit_event.output_ref == "pinned:false"
        assert unpinned.audit_event.action_ref == "unpin"
        assert unpinned.audit_event.lifecycle_revision == 2

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version = await tx.memory_versions.get_latest("memory_001")

        assert memory == unpinned.memory_item
        assert latest_version is None
        assert tuple(event.decision for event in store.audit_events) == ("pin", "unpin")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("initial_status", "action", "expected_status", "timestamp_field"),
    (
        (
            MemoryStatus.ACTIVE,
            LifecycleAction.ARCHIVE,
            MemoryStatus.ARCHIVED,
            "archived_at",
        ),
        (MemoryStatus.ACTIVE, LifecycleAction.HIDE, MemoryStatus.HIDDEN, "hidden_at"),
        (
            MemoryStatus.ACTIVE,
            LifecycleAction.INVALIDATE,
            MemoryStatus.INVALID,
            "invalidated_at",
        ),
        (MemoryStatus.ACTIVE, LifecycleAction.REMOVE, MemoryStatus.REMOVED, "removed_at"),
        (MemoryStatus.FADING, LifecycleAction.REVIEW, MemoryStatus.ACTIVE, "last_reviewed_at"),
        (
            MemoryStatus.NEEDS_REVIEW,
            LifecycleAction.CONFIRM,
            MemoryStatus.ACTIVE,
            "last_confirmed_at",
        ),
        (
            MemoryStatus.ARCHIVED,
            LifecycleAction.UNARCHIVE,
            MemoryStatus.ACTIVE,
            "activated_at",
        ),
        (MemoryStatus.HIDDEN, LifecycleAction.UNHIDE, MemoryStatus.ACTIVE, "activated_at"),
    ),
)
def test_status_transitions_update_action_timestamps_and_record_versions(
    initial_status: MemoryStatus,
    action: LifecycleAction,
    expected_status: MemoryStatus,
    timestamp_field: str,
) -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item(status=initial_status))

        result = await service.transition(
            _request(
                action=action,
                idempotency_key=f"lifecycle:memory_001:{action.value}",
                reason=f"{action.value} memory",
            )
        )

        assert result.previous_status is initial_status
        assert result.memory_item.status is expected_status
        assert result.memory_item.lifecycle_revision == 1
        assert result.memory_item.updated_at == NOW
        assert getattr(result.memory_item, timestamp_field) == NOW
        assert result.audit_event.input_ref == initial_status.value
        assert result.audit_event.output_ref == expected_status.value
        assert result.audit_event.action_ref == action.value
        assert result.audit_event.lifecycle_revision == 1

        async with store.transaction() as tx:
            latest_version = await tx.memory_versions.get_latest("memory_001")

        assert latest_version is not None
        assert latest_version.version == 1
        assert latest_version.status is expected_status

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("initial_status", "action", "expected_message"),
    (
        (
            MemoryStatus.ARCHIVED,
            LifecycleAction.HIDE,
            "hide is not allowed from archived",
        ),
        (MemoryStatus.REMOVED, LifecycleAction.CONFIRM, "removed memories are terminal"),
    ),
)
def test_illegal_transitions_raise_and_record_failure_audit_without_mutating_memory(
    initial_status: MemoryStatus,
    action: LifecycleAction,
    expected_message: str,
) -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)
    original = _memory_item(status=initial_status)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(original)

        with pytest.raises(DomainRuleViolation, match=expected_message):
            await service.transition(
                _request(
                    action=action,
                    idempotency_key=f"lifecycle:memory_001:illegal:{action.value}",
                    reason=f"Illegal {action.value}",
                )
            )

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version = await tx.memory_versions.get_latest("memory_001")
            audit = await tx.audit_events.get_by_idempotency_key(
                entity_type="memory_item",
                entity_id="memory_001",
                idempotency_key=f"lifecycle:memory_001:illegal:{action.value}",
            )

        assert memory == original
        assert latest_version is None
        assert audit is not None
        assert audit.stage == "lifecycle_transition.failed"
        assert audit.input_ref == initial_status.value
        assert audit.output_ref is None
        assert audit.decision == "rejected"
        assert audit.action_ref == action.value
        assert audit.lifecycle_revision == original.lifecycle_revision
        assert audit.reason_code == "invalid_lifecycle_transition"
        assert audit.reason_text == expected_message

    asyncio.run(scenario())


def test_successful_transition_replay_is_side_effect_idempotent() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item(status=MemoryStatus.CANDIDATE))

        request = _request(
            action=LifecycleAction.APPROVE,
            idempotency_key="lifecycle:memory_001:approve:idempotent",
        )
        first = await service.transition(request)
        replay = await service.transition(
            _request(
                action=LifecycleAction.APPROVE,
                idempotency_key="lifecycle:memory_001:approve:idempotent",
                now=datetime(2026, 4, 28, 10, 30, tzinfo=UTC),
            )
        )

        assert replay.previous_status is MemoryStatus.CANDIDATE
        assert replay.memory_item == first.memory_item
        assert replay.audit_event == first.audit_event
        assert len(store.audit_events) == 1

        async with store.transaction() as tx:
            latest_after_replay = await tx.memory_versions.get_latest("memory_001")

        assert latest_after_replay is not None
        assert latest_after_replay.version == 1

        await service.transition(
            _request(
                action=LifecycleAction.ARCHIVE,
                idempotency_key="lifecycle:memory_001:archive:after-replay",
                reason="Archive after replay check",
            )
        )
        async with store.transaction() as tx:
            latest_after_new_action = await tx.memory_versions.get_latest("memory_001")

        assert latest_after_new_action is not None
        assert latest_after_new_action.version == 2

    asyncio.run(scenario())


def test_successful_transition_replay_after_later_status_change_fails_without_side_effects() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item(status=MemoryStatus.CANDIDATE))

        original_request = _request(
            action=LifecycleAction.APPROVE,
            idempotency_key="lifecycle:memory_001:approve:stale-replay",
        )
        await service.transition(original_request)
        archived = await service.transition(
            _request(
                action=LifecycleAction.ARCHIVE,
                idempotency_key="lifecycle:memory_001:archive:before-stale-replay",
                reason="Archive before stale replay",
            )
        )
        audit_count_before_replay = len(store.audit_events)
        async with store.transaction() as tx:
            latest_version_before_replay = await tx.memory_versions.get_latest("memory_001")

        with pytest.raises(
            DomainRuleViolation,
            match="idempotent lifecycle replay no longer matches lifecycle revision",
        ):
            await service.transition(original_request)

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version_after_replay = await tx.memory_versions.get_latest("memory_001")

        assert memory == archived.memory_item
        assert latest_version_before_replay is not None
        assert latest_version_after_replay == latest_version_before_replay
        assert latest_version_after_replay.version == 2
        assert len(store.audit_events) == audit_count_before_replay

    asyncio.run(scenario())


def test_successful_transition_replay_after_state_changes_away_and_back_fails() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item(status=MemoryStatus.CANDIDATE))

        original_request = _request(
            action=LifecycleAction.APPROVE,
            idempotency_key="lifecycle:memory_001:approve:stale-after-return",
        )
        await service.transition(original_request)
        await service.transition(
            _request(
                action=LifecycleAction.ARCHIVE,
                idempotency_key="lifecycle:memory_001:archive:before-return",
                reason="Archive before returning active",
            )
        )
        returned = await service.transition(
            _request(
                action=LifecycleAction.UNARCHIVE,
                idempotency_key="lifecycle:memory_001:unarchive:before-return-replay",
                reason="Return to active before stale replay",
            )
        )
        audit_count_before_replay = len(store.audit_events)
        async with store.transaction() as tx:
            latest_version_before_replay = await tx.memory_versions.get_latest("memory_001")

        with pytest.raises(
            DomainRuleViolation,
            match="idempotent lifecycle replay no longer matches lifecycle revision",
        ):
            await service.transition(original_request)

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version_after_replay = await tx.memory_versions.get_latest("memory_001")

        assert memory == returned.memory_item
        assert latest_version_before_replay is not None
        assert latest_version_after_replay == latest_version_before_replay
        assert latest_version_after_replay.version == 3
        assert len(store.audit_events) == audit_count_before_replay

    asyncio.run(scenario())


def test_replay_with_same_idempotency_key_and_different_action_fails_without_side_effects() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(_memory_item(status=MemoryStatus.CANDIDATE))

        idempotency_key = "lifecycle:memory_001:reused-key"
        approved = await service.transition(
            _request(action=LifecycleAction.APPROVE, idempotency_key=idempotency_key)
        )
        audit_count_before_replay = len(store.audit_events)
        async with store.transaction() as tx:
            latest_version_before_replay = await tx.memory_versions.get_latest("memory_001")

        with pytest.raises(
            DomainRuleViolation,
            match="idempotency key was already used for approve",
        ):
            await service.transition(
                _request(
                    action=LifecycleAction.ARCHIVE,
                    idempotency_key=idempotency_key,
                    reason="Archive with reused key",
                )
            )

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version_after_replay = await tx.memory_versions.get_latest("memory_001")

        assert memory == approved.memory_item
        assert latest_version_before_replay is not None
        assert latest_version_after_replay == latest_version_before_replay
        assert latest_version_after_replay.version == 1
        assert len(store.audit_events) == audit_count_before_replay

    asyncio.run(scenario())


def test_failed_transition_replay_is_side_effect_idempotent() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)
    original = _memory_item(status=MemoryStatus.ARCHIVED)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(original)

        request = _request(
            action=LifecycleAction.HIDE,
            idempotency_key="lifecycle:memory_001:hide:failed-replay",
            reason="Attempt hidden archive",
        )
        with pytest.raises(DomainRuleViolation, match="hide is not allowed from archived"):
            await service.transition(request)
        with pytest.raises(DomainRuleViolation, match="hide is not allowed from archived"):
            await service.transition(request)

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version = await tx.memory_versions.get_latest("memory_001")

        assert memory == original
        assert latest_version is None
        assert len(store.audit_events) == 1
        assert store.audit_events[0].stage == "lifecycle_transition.failed"

    asyncio.run(scenario())


def test_failed_transition_replay_with_different_action_fails_key_action_match_first() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)
    original = _memory_item(status=MemoryStatus.ARCHIVED)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(original)

        failed_request = _request(
            action=LifecycleAction.HIDE,
            idempotency_key="lifecycle:memory_001:failed-key-action",
            reason="Attempt hidden archive",
        )
        with pytest.raises(DomainRuleViolation, match="hide is not allowed from archived"):
            await service.transition(failed_request)

        audit_count_before_replay = len(store.audit_events)
        with pytest.raises(
            DomainRuleViolation,
            match="idempotency key was already used for hide; cannot replay unarchive",
        ):
            await service.transition(
                _request(
                    action=LifecycleAction.UNARCHIVE,
                    idempotency_key="lifecycle:memory_001:failed-key-action",
                    reason="Reuse failed key for a different action",
                )
            )

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version = await tx.memory_versions.get_latest("memory_001")

        assert memory == original
        assert latest_version is None
        assert len(store.audit_events) == audit_count_before_replay

    asyncio.run(scenario())


def test_new_transition_uses_get_for_update_before_applying_transition() -> None:
    memory = _memory_item(status=MemoryStatus.CANDIDATE)
    unit_of_work = _TrackingUnitOfWork(memory)
    service = LifecycleTransitionService(unit_of_work)

    async def scenario() -> None:
        result = await service.transition(
            _request(
                action=LifecycleAction.APPROVE,
                idempotency_key="lifecycle:memory_001:get-for-update",
            )
        )

        assert result.memory_item.status is MemoryStatus.ACTIVE
        assert unit_of_work.memory_items.get_for_update_calls == ["memory_001"]
        assert unit_of_work.memory_items.get_calls == []

    asyncio.run(scenario())


def _request(
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


def _memory_item(
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


class _TrackingUnitOfWork:
    def __init__(self, memory: MemoryItem) -> None:
        self.audit_events = _TrackingAuditEventRepository()
        self.memory_items = _TrackingMemoryItemRepository(memory)
        self.memory_versions = _TrackingMemoryVersionRepository()

    def transaction(self) -> "_TrackingUnitOfWork":
        return self

    async def __aenter__(self) -> "_TrackingUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class _TrackingAuditEventRepository:
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


class _TrackingMemoryItemRepository:
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


class _TrackingMemoryVersionRepository:
    def __init__(self) -> None:
        self.versions: list[MemoryVersion] = []

    async def record(self, version: MemoryVersion) -> MemoryVersion:
        self.versions.append(version)
        return version

    async def get_latest(self, memory_id: str) -> MemoryVersion | None:
        versions = [version for version in self.versions if version.memory_id == memory_id]
        versions.sort(key=lambda version: version.version, reverse=True)
        return versions[0] if versions else None
