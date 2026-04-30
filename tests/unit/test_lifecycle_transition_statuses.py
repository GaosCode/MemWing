import asyncio

import pytest

from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import MemoryStatus
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from tests.unit.test_lifecycle_transition_fixtures import (
    NOW,
    lifecycle_request,
    memory_item,
)


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
            await tx.memory_items.upsert(memory_item(status=initial_status))

        result = await service.transition(
            lifecycle_request(
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
