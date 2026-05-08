from __future__ import annotations

from datetime import datetime
from typing import Protocol

from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope


class SourceEventRepositoryPort(Protocol):
    async def insert_if_absent(self, event: SourceEvent) -> tuple[SourceEvent, bool]:
        ...

    async def get_source_event(self, source_event_id: str) -> SourceEvent | None:
        ...

    async def redact_source_event(
        self,
        *,
        source_event_id: str,
        redacted_content: str,
        purged_at: datetime,
        purged_by: str,
        purge_reason: str,
        purge_level: str,
        graph_backend_raw_retained: bool,
    ) -> SourceEvent | None:
        ...

    async def list_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[SourceEvent, ...]:
        ...

    async def list_recent_for_scope(
        self,
        *,
        scope: EffectiveScope,
        limit: int,
    ) -> tuple[SourceEvent, ...]:
        ...
