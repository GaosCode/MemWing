import asyncio

import pytest

from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.errors import DomainRuleViolation
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import MemoryStatus
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from tests.unit.test_lifecycle_transition_fixtures import (
    NOW,
    lifecycle_request,
    memory_item,
)


def test_candidate_approve_activates_memory_and_records_version_and_audit() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(memory_item(status=MemoryStatus.CANDIDATE))

        result = await service.transition(
            lifecycle_request(
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
            await tx.memory_items.upsert(memory_item(status=MemoryStatus.ACTIVE))

        pinned = await service.transition(
            lifecycle_request(
                action=LifecycleAction.PIN,
                idempotency_key="lifecycle:memory_001:pin",
                reason="Pin high value decision",
            )
        )
        unpinned = await service.transition(
            lifecycle_request(
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
    original = memory_item(status=initial_status)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(original)

        with pytest.raises(DomainRuleViolation, match=expected_message):
            await service.transition(
                lifecycle_request(
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
