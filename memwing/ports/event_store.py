from __future__ import annotations

from typing import Protocol, runtime_checkable

from memwing.api.agent_runtime import RememberEventResult
from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope


@runtime_checkable
class EventStorePort(Protocol):
    async def remember_event(self, event: SourceEvent) -> RememberEventResult:
        ...

    async def get_source_event(
        self, source_event_id: str, scope: EffectiveScope
    ) -> SourceEvent | None:
        ...
