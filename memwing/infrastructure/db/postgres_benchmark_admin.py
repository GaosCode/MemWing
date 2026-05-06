from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from memwing.ports.benchmark_admin import (
    BenchmarkAdminStorePort,
    BenchmarkCleanupResult,
    BenchmarkRuntimeBinding,
    BenchmarkScope,
)


class _BenchmarkAdminConnection(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[object]:
        ...

    async def fetchrow(self, sql: str, params: dict[str, object]) -> Mapping[str, object] | None:
        ...

    async def fetch(self, sql: str, params: dict[str, object]) -> tuple[Mapping[str, object], ...]:
        ...


class PostgresBenchmarkAdminStore(BenchmarkAdminStorePort):
    def __init__(self, connection: _BenchmarkAdminConnection) -> None:
        self._connection = connection

    async def prepare_scope(
        self,
        *,
        scope: BenchmarkScope,
        runtime_binding: BenchmarkRuntimeBinding,
    ) -> None:
        async with self._connection.transaction():
            await self._prepare_scope(scope=scope, runtime_binding=runtime_binding)

    async def cleanup_scope(
        self,
        *,
        scope: BenchmarkScope,
        runtime_binding: BenchmarkRuntimeBinding,
    ) -> BenchmarkCleanupResult:
        async with self._connection.transaction():
            deleted_counts = {
                name: await self._delete_count(sql, scope)
                for name, sql in _DELETE_SQL
            }
            await self._prepare_scope(scope=scope, runtime_binding=runtime_binding)
        return BenchmarkCleanupResult(deleted_counts=deleted_counts, prepared=True)

    async def _delete_count(self, sql: str, scope: BenchmarkScope) -> int:
        rows = await self._connection.fetch(
            sql,
            {"project_memory_space_id": scope.project_memory_space_id},
        )
        return len(rows)

    async def _prepare_scope(
        self,
        *,
        scope: BenchmarkScope,
        runtime_binding: BenchmarkRuntimeBinding,
    ) -> None:
        await self._connection.fetchrow(
            """
            INSERT INTO project_memory_spaces (id, name, default_safe_mode_enabled)
            VALUES (%(project_memory_space_id)s, %(project_name)s, false)
            ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name,
                default_safe_mode_enabled = EXCLUDED.default_safe_mode_enabled,
                updated_at = now()
            RETURNING id
            """,
            {
                "project_memory_space_id": scope.project_memory_space_id,
                "project_name": f"Benchmark {scope.project_memory_space_id}",
            },
        )
        if scope.group_id is not None:
            await self._connection.fetchrow(
                """
                INSERT INTO group_memory_settings (
                    project_memory_space_id, group_id, safe_mode_enabled, shared_group_id
                )
                VALUES (
                    %(project_memory_space_id)s,
                    %(group_id)s,
                    true,
                    %(shared_group_id)s
                )
                ON CONFLICT (project_memory_space_id, group_id) DO UPDATE
                SET safe_mode_enabled = EXCLUDED.safe_mode_enabled,
                    shared_group_id = EXCLUDED.shared_group_id,
                    updated_at = now()
                RETURNING group_id
                """,
                {
                    "project_memory_space_id": scope.project_memory_space_id,
                    "group_id": scope.group_id,
                    "shared_group_id": scope.shared_group_id,
                },
            )
        await self._connection.fetchrow(
            """
            INSERT INTO runtime_scope_bindings (
                runtime, agent_id, workspace_id, session_key_pattern, project_memory_space_id
            )
            VALUES (
                %(runtime)s,
                %(agent_id)s,
                %(workspace_id)s,
                %(session_key_pattern)s,
                %(project_memory_space_id)s
            )
            ON CONFLICT (
                runtime,
                agent_id,
                (COALESCE(workspace_id, '')),
                session_key_pattern
            )
            DO UPDATE
            SET project_memory_space_id = EXCLUDED.project_memory_space_id,
                updated_at = now()
            RETURNING id
            """,
            {
                "runtime": runtime_binding.runtime,
                "agent_id": runtime_binding.agent_id,
                "workspace_id": runtime_binding.workspace_id,
                "session_key_pattern": runtime_binding.session_id or "",
                "project_memory_space_id": scope.project_memory_space_id,
            },
        )


_DELETE_SQL: tuple[tuple[str, str], ...] = (
    (
        "memory_recall_events",
        """
        DELETE FROM memory_recall_events
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "memory_graph_links",
        """
        DELETE FROM memory_graph_links
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "graph_write_jobs",
        """
        DELETE FROM graph_write_jobs
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "memory_page_versions",
        """
        DELETE FROM memory_page_versions
        WHERE page_id IN (
            SELECT id FROM memory_pages
            WHERE project_memory_space_id = %(project_memory_space_id)s
        )
        RETURNING id
        """,
    ),
    (
        "memory_pages",
        """
        DELETE FROM memory_pages
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "memory_versions",
        """
        DELETE FROM memory_versions
        WHERE memory_id IN (
            SELECT id FROM memory_items
            WHERE project_memory_space_id = %(project_memory_space_id)s
        )
        RETURNING id
        """,
    ),
    (
        "push_candidates",
        """
        DELETE FROM push_candidates
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "forgetting_review_candidates",
        """
        DELETE FROM forgetting_review_candidates
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "memory_items",
        """
        DELETE FROM memory_items
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "working_memory_entries",
        """
        DELETE FROM working_memory_entries
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "evidence_chunks",
        """
        DELETE FROM evidence_chunks
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "outbox_jobs",
        """
        DELETE FROM outbox_jobs
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "audit_events",
        """
        DELETE FROM audit_events
        WHERE entity_id = %(project_memory_space_id)s
           OR source_event_ids && ARRAY(
                SELECT id FROM source_events
                WHERE project_memory_space_id = %(project_memory_space_id)s
           )
           OR entity_id IN (
                SELECT id FROM source_events
                WHERE project_memory_space_id = %(project_memory_space_id)s
           )
        RETURNING id
        """,
    ),
    (
        "source_events",
        """
        DELETE FROM source_events
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "group_memory_settings",
        """
        DELETE FROM group_memory_settings
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING group_id
        """,
    ),
    (
        "runtime_scope_bindings",
        """
        DELETE FROM runtime_scope_bindings
        WHERE project_memory_space_id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
    (
        "project_memory_spaces",
        """
        DELETE FROM project_memory_spaces
        WHERE id = %(project_memory_space_id)s
        RETURNING id
        """,
    ),
)
