import asyncio
from datetime import UTC, datetime

import pytest

from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.errors import DomainRuleViolation
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import MemoryStatus
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from tests.unit.test_lifecycle_transition_fixtures import (
    lifecycle_request,
    memory_item,
)


def test_successful_transition_replay_is_side_effect_idempotent() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(memory_item(status=MemoryStatus.CANDIDATE))

        request = lifecycle_request(
            action=LifecycleAction.APPROVE,
            idempotency_key="lifecycle:memory_001:approve:idempotent",
        )
        first = await service.transition(request)
        replay = await service.transition(
            lifecycle_request(
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
            lifecycle_request(
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
            await tx.memory_items.upsert(memory_item(status=MemoryStatus.CANDIDATE))

        original_request = lifecycle_request(
            action=LifecycleAction.APPROVE,
            idempotency_key="lifecycle:memory_001:approve:stale-replay",
        )
        await service.transition(original_request)
        archived = await service.transition(
            lifecycle_request(
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
            await tx.memory_items.upsert(memory_item(status=MemoryStatus.CANDIDATE))

        original_request = lifecycle_request(
            action=LifecycleAction.APPROVE,
            idempotency_key="lifecycle:memory_001:approve:stale-after-return",
        )
        await service.transition(original_request)
        await service.transition(
            lifecycle_request(
                action=LifecycleAction.ARCHIVE,
                idempotency_key="lifecycle:memory_001:archive:before-return",
                reason="Archive before returning active",
            )
        )
        returned = await service.transition(
            lifecycle_request(
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
            await tx.memory_items.upsert(memory_item(status=MemoryStatus.CANDIDATE))

        idempotency_key = "lifecycle:memory_001:reused-key"
        approved = await service.transition(
            lifecycle_request(action=LifecycleAction.APPROVE, idempotency_key=idempotency_key)
        )
        audit_count_before_replay = len(store.audit_events)
        async with store.transaction() as tx:
            latest_version_before_replay = await tx.memory_versions.get_latest("memory_001")

        with pytest.raises(
            DomainRuleViolation,
            match="idempotency key was already used for approve",
        ):
            await service.transition(
                lifecycle_request(
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
    original = memory_item(status=MemoryStatus.ARCHIVED)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(original)

        request = lifecycle_request(
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


def test_failed_transition_replay_after_lifecycle_revision_changes_fails_without_side_effects() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)
    original = memory_item(status=MemoryStatus.ARCHIVED)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(original)

        failed_request = lifecycle_request(
            action=LifecycleAction.HIDE,
            idempotency_key="lifecycle:memory_001:hide:failed-stale-replay",
            reason="Attempt hidden archive",
        )
        with pytest.raises(DomainRuleViolation, match="hide is not allowed from archived"):
            await service.transition(failed_request)

        unarchived = await service.transition(
            lifecycle_request(
                action=LifecycleAction.UNARCHIVE,
                idempotency_key="lifecycle:memory_001:unarchive:before-failed-replay",
                reason="Unarchive before failed replay",
            )
        )
        audit_count_before_replay = len(store.audit_events)
        async with store.transaction() as tx:
            latest_version_before_replay = await tx.memory_versions.get_latest("memory_001")

        with pytest.raises(
            DomainRuleViolation,
            match="idempotent lifecycle replay no longer matches lifecycle revision",
        ):
            await service.transition(failed_request)

        async with store.transaction() as tx:
            memory = await tx.memory_items.get("memory_001")
            latest_version_after_replay = await tx.memory_versions.get_latest("memory_001")

        assert memory == unarchived.memory_item
        assert latest_version_before_replay is not None
        assert latest_version_after_replay == latest_version_before_replay
        assert latest_version_after_replay.version == 1
        assert len(store.audit_events) == audit_count_before_replay

    asyncio.run(scenario())


def test_failed_transition_replay_with_different_action_fails_key_action_match_first() -> None:
    store = InMemoryDataStore()
    service = LifecycleTransitionService(store)
    original = memory_item(status=MemoryStatus.ARCHIVED)

    async def scenario() -> None:
        async with store.transaction() as tx:
            await tx.memory_items.upsert(original)

        failed_request = lifecycle_request(
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
                lifecycle_request(
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
