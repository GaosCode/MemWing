from __future__ import annotations

from typing import Protocol

from memwing.core.models import AuditEvent


class AuditEventRepositoryPort(Protocol):
    async def record(self, event: AuditEvent) -> AuditEvent:
        ...

    async def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
        limit: int,
    ) -> tuple[AuditEvent, ...]:
        ...

    async def get_by_idempotency_key(
        self,
        *,
        entity_type: str,
        entity_id: str,
        idempotency_key: str,
    ) -> AuditEvent | None:
        ...
