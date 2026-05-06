from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from collections.abc import Mapping
from typing import Protocol


class PostgresSchemaConnection(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[object]:
        ...

    async def execute(self, sql: str, params: Mapping[str, object] | None = None) -> None:
        ...


async def ensure_postgres_schema_compatibility(connection: PostgresSchemaConnection) -> None:
    async with connection.transaction():
        await connection.execute(_SCHEMA_COMPATIBILITY_LOCK_SQL)
        for statement in _GRAPH_WRITE_SERIALIZATION_KEY_PATCH_SQL:
            await connection.execute(statement)
        for statement in _MODEL_RESULT_CACHE_PATCH_SQL:
            await connection.execute(statement)


_SCHEMA_COMPATIBILITY_LOCK_SQL = """
SELECT pg_advisory_xact_lock(hashtext('memwing:schema_compatibility'))
"""

_GRAPH_WRITE_SERIALIZATION_KEY_PATCH_SQL = (
    """
    ALTER TABLE graph_write_jobs
        ADD COLUMN IF NOT EXISTS serialization_key text
    """,
    """
    UPDATE graph_write_jobs
    SET serialization_key = 'backend:' || backend || ':project:' || project_memory_space_id
    WHERE serialization_key IS NULL
    """,
    """
    ALTER TABLE graph_write_jobs
        ALTER COLUMN serialization_key SET NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_graph_write_jobs_status_serialization_lock
        ON graph_write_jobs (status, serialization_key, lock_expires_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_graph_write_jobs_project_status_serialization
        ON graph_write_jobs (project_memory_space_id, status, serialization_key)
    """,
)

_MODEL_RESULT_CACHE_PATCH_SQL = (
    """
    CREATE TABLE IF NOT EXISTS model_result_cache (
        id text PRIMARY KEY,
        project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
        cache_kind text NOT NULL,
        role text NOT NULL,
        runtime text NOT NULL,
        model text NOT NULL,
        transport text NOT NULL,
        prompt_hash text NOT NULL,
        input_hash text NOT NULL,
        schema_hash text NOT NULL,
        source_event_ids text[] NOT NULL,
        value_json jsonb NOT NULL DEFAULT '{}'::jsonb,
        embedding_vector double precision[],
        status text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_hit_at timestamptz,
        hit_count integer NOT NULL DEFAULT 0,
        invalidated_at timestamptz,
        invalidated_reason text,
        expires_at timestamptz
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_model_result_cache_key
        ON model_result_cache (
            project_memory_space_id,
            cache_kind,
            role,
            runtime,
            model,
            transport,
            prompt_hash,
            input_hash,
            schema_hash
        )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_model_result_cache_source_event_ids
        ON model_result_cache USING gin (source_event_ids)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_model_result_cache_project_status
        ON model_result_cache (project_memory_space_id, status)
    """,
)


__all__ = ("ensure_postgres_schema_compatibility",)
