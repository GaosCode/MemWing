from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from memwing.api.runtime_config import database_url_from_env
from memwing.application.access_service import MemoryAccessService
from memwing.application.gateway_service import MemoryGateway
from memwing.application.scope_resolver import ScopeResolver
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter
from memwing.infrastructure.db.postgres import PostgresDataStore
from memwing.infrastructure.db.postgres_connection import PooledPostgresConnection
from memwing.ports.event_store import EventStoreUnitOfWorkPort


@dataclass(frozen=True, slots=True)
class OpenClawRuntimeHandle:
    runtime: OpenClawAdapter
    connection: PooledPostgresConnection

    async def close(self) -> None:
        await self.connection.close()


def create_openclaw_adapter_from_store(store: EventStoreUnitOfWorkPort) -> OpenClawAdapter:
    scope_resolver = ScopeResolver(store)
    return OpenClawAdapter(
        MemoryGateway(store, scope_resolver),
        MemoryAccessService(scope_resolver, store),
    )


async def create_openclaw_adapter_from_postgres(
    database_url: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> OpenClawRuntimeHandle:
    connection = await PooledPostgresConnection.connect(
        database_url,
        min_size=min_size,
        max_size=max_size,
    )
    runtime = create_openclaw_adapter_from_store(PostgresDataStore(connection))
    return OpenClawRuntimeHandle(runtime=runtime, connection=connection)


async def create_openclaw_adapter_from_env(
    env: Mapping[str, str] | None = None,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> OpenClawRuntimeHandle:
    return await create_openclaw_adapter_from_postgres(
        database_url_from_env(env),
        min_size=min_size,
        max_size=max_size,
    )


__all__ = (
    "OpenClawRuntimeHandle",
    "create_openclaw_adapter_from_env",
    "create_openclaw_adapter_from_postgres",
    "create_openclaw_adapter_from_store",
)
