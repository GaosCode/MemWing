from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from memwing.core.models import LongTermFilterItem, SourceEvent
from memwing.core.scope import EffectiveScope


@runtime_checkable
class LongTermFilterPort(Protocol):
    async def filter_events(
        self, events: Sequence[SourceEvent], scope: EffectiveScope
    ) -> tuple[LongTermFilterItem, ...]:
        ...
