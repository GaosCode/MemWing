from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from memwing.core.scope import (
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
    ProjectMemorySpaceDirectoryGroupRecord,
    ProjectMemorySpaceDirectoryRecord,
    ProjectMemorySpaceDirectoryThreadRecord,
    RuntimeScopeBinding,
)

from .postgres_sql import SESSION_KEY_PATTERN_LIKE_SQL
from .postgres_evidence_repositories import (
    PostgresEvidenceChunkRepository,
    PostgresWorkingMemoryRepository,
)
from .postgres_graph_repositories import (
    PostgresGraphWriteJobRepository,
    PostgresMemoryGraphLinkRepository,
)
from .postgres_forgetting_review_repositories import PostgresForgettingReviewCandidateRepository
from .postgres_memory_repositories import (
    PostgresMemoryItemRepository,
    PostgresMemoryPageRepository,
    PostgresMemoryPageVersionRepository,
    PostgresMemoryRecallEventRepository,
    PostgresMemoryVersionRepository,
)
from .postgres_model_cache import PostgresModelResultCacheRepository
from .postgres_repositories import (
    PostgresAuditEventRepository,
    PostgresExecutor,
    PostgresOutboxJobRepository,
    PostgresSourceEventRepository,
)
from .postgres_push_repositories import PostgresPushCandidateRepository
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

    async def list_project_memory_space_directory(
        self,
        *,
        include_benchmark: bool,
        query: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[ProjectMemorySpaceDirectoryRecord, ...]:
        del cursor
        rows = await self._connection.fetch(
            """
            SELECT
                p.id,
                p.name,
                p.default_safe_mode_enabled,
                COUNT(DISTINCT m.id) AS memory_count,
                COUNT(DISTINCT s.id) AS source_event_count,
                COUNT(DISTINCT pg.id) AS page_count,
                GREATEST(
                    p.updated_at,
                    COALESCE(MAX(m.updated_at), p.updated_at),
                    COALESCE(MAX(s.created_at), p.updated_at),
                    COALESCE(MAX(pg.updated_at), p.updated_at)
                ) AS directory_updated_at
            FROM project_memory_spaces p
            LEFT JOIN memory_items m
                ON m.project_memory_space_id = p.id
            LEFT JOIN source_events s
                ON s.project_memory_space_id = p.id
            LEFT JOIN memory_pages pg
                ON pg.project_memory_space_id = p.id
            WHERE (%(include_benchmark)s OR p.id NOT LIKE %(benchmark_pattern)s)
              AND (
                %(query_pattern)s::text IS NULL
                OR p.id ILIKE %(query_pattern)s
                OR p.name ILIKE %(query_pattern)s
              )
            GROUP BY p.id, p.name, p.default_safe_mode_enabled, p.updated_at
            ORDER BY directory_updated_at DESC, p.id ASC
            LIMIT %(limit)s
            """,
            {
                "include_benchmark": include_benchmark,
                "benchmark_pattern": "benchmark:%",
                "query_pattern": f"%{query.strip()}%" if query and query.strip() else None,
                "limit": limit,
            },
        )
        records = []
        for row in rows:
            project = ProjectMemorySpace(
                id=str(row["id"]),
                name=str(row["name"]),
                default_safe_mode_enabled=bool(row["default_safe_mode_enabled"]),
            )
            records.append(
                ProjectMemorySpaceDirectoryRecord(
                    project=project,
                    memory_count=int(row["memory_count"]),
                    source_event_count=int(row["source_event_count"]),
                    page_count=int(row["page_count"]),
                    updated_at=row["directory_updated_at"],
                    groups=await self._list_project_directory_groups(project),
                )
            )
        return tuple(records)

    async def _list_project_directory_groups(
        self,
        project: ProjectMemorySpace,
    ) -> tuple[ProjectMemorySpaceDirectoryGroupRecord, ...]:
        rows = await self._connection.fetch(
            """
            WITH scope_rows AS (
                SELECT
                    project_memory_space_id,
                    group_id,
                    thread_id,
                    updated_at,
                    id,
                    'memory' AS kind
                FROM memory_items
                UNION ALL
                SELECT
                    project_memory_space_id,
                    group_id,
                    thread_id,
                    created_at AS updated_at,
                    id,
                    'source' AS kind
                FROM source_events
                UNION ALL
                SELECT
                    project_memory_space_id,
                    group_id,
                    thread_id,
                    updated_at,
                    id,
                    'page' AS kind
                FROM memory_pages
            )
            SELECT
                r.group_id,
                r.thread_id,
                COALESCE(g.safe_mode_enabled, %(project_safe_mode)s) AS safe_mode_enabled,
                g.shared_group_id,
                COUNT(DISTINCT r.id) FILTER (WHERE r.kind = 'memory') AS memory_count,
                COUNT(DISTINCT r.id) FILTER (WHERE r.kind = 'source') AS source_event_count,
                MAX(r.updated_at) AS updated_at
            FROM scope_rows r
            LEFT JOIN group_memory_settings g
                ON g.project_memory_space_id = r.project_memory_space_id
               AND g.group_id = r.group_id
            WHERE r.project_memory_space_id = %(project_memory_space_id)s
              AND r.group_id IS NOT NULL
            GROUP BY r.group_id, r.thread_id, g.safe_mode_enabled, g.shared_group_id
            ORDER BY r.group_id ASC, r.thread_id ASC
            """,
            {
                "project_memory_space_id": project.id,
                "project_safe_mode": project.default_safe_mode_enabled,
            },
        )
        groups_by_id: dict[str, list[Row]] = {}
        for row in rows:
            groups_by_id.setdefault(str(row["group_id"]), []).append(row)
        groups = []
        for group_id, group_rows in groups_by_id.items():
            group_memory_count = sum(int(row["memory_count"]) for row in group_rows)
            group_source_event_count = sum(int(row["source_event_count"]) for row in group_rows)
            groups.append(
                ProjectMemorySpaceDirectoryGroupRecord(
                    group_id=group_id,
                    safe_mode_enabled=bool(group_rows[0]["safe_mode_enabled"]),
                    shared_group_id=(
                        str(group_rows[0]["shared_group_id"])
                        if group_rows[0]["shared_group_id"] is not None
                        else None
                    ),
                    memory_count=group_memory_count,
                    source_event_count=group_source_event_count,
                    threads=tuple(
                        ProjectMemorySpaceDirectoryThreadRecord(
                            thread_id=str(row["thread_id"]),
                            memory_count=int(row["memory_count"]),
                            source_event_count=int(row["source_event_count"]),
                            updated_at=row["updated_at"],
                        )
                        for row in group_rows
                        if row["thread_id"] is not None
                    ),
                )
            )
        return tuple(groups)

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
        self.evidence_chunks = PostgresEvidenceChunkRepository(self)
        self.working_memory_entries = PostgresWorkingMemoryRepository(self)
        self.memory_recall_events = PostgresMemoryRecallEventRepository(self)
        self.memory_items = PostgresMemoryItemRepository(self)
        self.memory_versions = PostgresMemoryVersionRepository(self)
        self.memory_pages = PostgresMemoryPageRepository(self)
        self.memory_page_versions = PostgresMemoryPageVersionRepository(self)
        self.graph_write_jobs = PostgresGraphWriteJobRepository(self)
        self.memory_graph_links = PostgresMemoryGraphLinkRepository(self)
        self.forgetting_review_candidates = PostgresForgettingReviewCandidateRepository(self)
        self.push_candidates = PostgresPushCandidateRepository(self)
        self.model_result_cache = PostgresModelResultCacheRepository(self)

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
