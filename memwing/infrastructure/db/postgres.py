from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from memwing.core.scope import (
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)

from .postgres_sql import SESSION_KEY_PATTERN_LIKE_SQL
from .postgres_repositories import (
    PostgresAuditEventRepository,
    PostgresExecutor,
    PostgresOutboxJobRepository,
    PostgresSourceEventRepository,
)
from .postgres_rows import (
    Row,
    group_memory_settings_from_row,
    platform_scope_binding_from_row,
    project_memory_space_from_row,
    runtime_scope_binding_from_row,
)


class AsyncPostgresConnection(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[object]:
        ...

    async def fetchrow(self, sql: str, params: Mapping[str, object]) -> Row | None:
        ...

    async def fetch(self, sql: str, params: Mapping[str, object]) -> tuple[Row, ...]:
        ...


class PostgresDataStore:
    def __init__(self, connection: AsyncPostgresConnection) -> None:
        self._connection = connection

    def transaction(self) -> PostgresTransaction:
        return PostgresTransaction(self._connection)

    async def get_project_memory_space(
        self,
        project_memory_space_id: str,
    ) -> ProjectMemorySpace | None:
        row = await self._connection.fetchrow(
            """
            SELECT id, name, default_safe_mode_enabled
            FROM project_memory_spaces
            WHERE id = %(project_memory_space_id)s
            """,
            {"project_memory_space_id": project_memory_space_id},
        )
        return project_memory_space_from_row(row) if row is not None else None

    async def list_runtime_scope_binding_candidates(
        self,
        *,
        runtime: str,
        agent_id: str,
        workspace_id: str | None,
        session_id: str | None,
    ) -> tuple[RuntimeScopeBinding, ...]:
        rows = await self._connection.fetch(
            f"""
            SELECT runtime, agent_id, workspace_id, session_key_pattern, project_memory_space_id
            FROM runtime_scope_bindings
            WHERE runtime = %(runtime)s
              AND agent_id = %(agent_id)s
              AND workspace_id IS NOT DISTINCT FROM %(workspace_id)s
              AND COALESCE(%(session_id)s, '') LIKE {SESSION_KEY_PATTERN_LIKE_SQL}
            """,
            {
                "runtime": runtime,
                "agent_id": agent_id,
                "workspace_id": workspace_id,
                "session_id": session_id,
            },
        )
        return tuple(runtime_scope_binding_from_row(row) for row in rows)

    async def list_platform_scope_binding_candidates(
        self,
        *,
        platform: str,
        tenant_id: str | None,
        channel_id: str,
        thread_id: str | None,
    ) -> tuple[PlatformScopeBinding, ...]:
        rows = await self._connection.fetch(
            """
            SELECT platform, tenant_id, channel_id, thread_id, project_memory_space_id, group_id
            FROM platform_scope_bindings
            WHERE platform = %(platform)s
              AND tenant_id IS NOT DISTINCT FROM %(tenant_id)s
              AND channel_id = %(channel_id)s
              AND (thread_id IS NOT DISTINCT FROM %(thread_id)s OR thread_id IS NULL)
            """,
            {
                "platform": platform,
                "tenant_id": tenant_id,
                "channel_id": channel_id,
                "thread_id": thread_id,
            },
        )
        return tuple(platform_scope_binding_from_row(row) for row in rows)

    async def get_group_memory_settings(
        self,
        *,
        project_memory_space_id: str,
        group_id: str,
    ) -> GroupMemorySettings | None:
        row = await self._connection.fetchrow(
            """
            SELECT project_memory_space_id, group_id, safe_mode_enabled, shared_group_id
            FROM group_memory_settings
            WHERE project_memory_space_id = %(project_memory_space_id)s
              AND group_id = %(group_id)s
            """,
            {"project_memory_space_id": project_memory_space_id, "group_id": group_id},
        )
        return group_memory_settings_from_row(row) if row is not None else None


class PostgresTransaction(PostgresExecutor):
    def __init__(self, connection: AsyncPostgresConnection) -> None:
        self._connection = connection
        self._context: AbstractAsyncContextManager[object] | None = None
        self.source_events = PostgresSourceEventRepository(self)
        self.audit_events = PostgresAuditEventRepository(self)
        self.outbox_jobs = PostgresOutboxJobRepository(self)

    async def __aenter__(self) -> PostgresTransaction:
        self._context = self._connection.transaction()
        await self._context.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if self._context is None:
            raise RuntimeError("Postgres transaction was not entered")
        return await self._context.__aexit__(exc_type, exc, traceback)

    async def fetchrow(self, sql: str, params: Mapping[str, object]) -> Row | None:
        return await self._connection.fetchrow(sql, params)

    async def fetch(self, sql: str, params: Mapping[str, object]) -> tuple[Row, ...]:
        return await self._connection.fetch(sql, params)
