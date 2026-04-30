import asyncio

from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.core.lifecycle import LifecycleAction
from memwing.core.models import MemoryStatus
from tests.unit.test_lifecycle_transition_fixtures import (
    TrackingUnitOfWork,
    lifecycle_request,
    memory_item,
)


def test_new_transition_uses_get_for_update_before_applying_transition() -> None:
    memory = memory_item(status=MemoryStatus.CANDIDATE)
    unit_of_work = TrackingUnitOfWork(memory)
    service = LifecycleTransitionService(unit_of_work)

    async def scenario() -> None:
        result = await service.transition(
            lifecycle_request(
                action=LifecycleAction.APPROVE,
                idempotency_key="lifecycle:memory_001:get-for-update",
            )
        )

        assert result.memory_item.status is MemoryStatus.ACTIVE
        assert unit_of_work.memory_items.get_for_update_calls == ["memory_001"]
        assert unit_of_work.memory_items.get_calls == []

    asyncio.run(scenario())
