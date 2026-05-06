from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager

from memwing.infrastructure.db.postgres_schema import ensure_postgres_schema_compatibility


def test_schema_compatibility_patch_repairs_graph_write_serialization_key() -> None:
    async def run() -> _FakeSchemaConnection:
        connection = _FakeSchemaConnection()

        await ensure_postgres_schema_compatibility(connection)

        return connection

    connection = asyncio.run(run())
    sql = "\n".join(connection.statements)

    assert connection.transaction_enters == 1
    assert connection.transaction_exits == 1
    assert "pg_advisory_xact_lock" in connection.statements[0]
    assert "ADD COLUMN IF NOT EXISTS serialization_key text" in sql
    assert "SET serialization_key = 'backend:' || backend || ':project:'" in sql
    assert "ALTER COLUMN serialization_key SET NOT NULL" in sql
    assert "idx_graph_write_jobs_status_serialization_lock" in sql
    assert "idx_graph_write_jobs_project_status_serialization" in sql
    assert "CREATE TABLE IF NOT EXISTS model_result_cache" in sql
    assert "source_event_ids text[] NOT NULL" in sql
    assert "embedding_vector double precision[]" in sql
    assert "uq_model_result_cache_key" in sql
    assert "idx_model_result_cache_source_event_ids" in sql
    assert "idx_model_result_cache_project_status" in sql


class _FakeSchemaConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.transaction_enters = 0
        self.transaction_exits = 0

    def transaction(self) -> AbstractAsyncContextManager[object]:
        return _FakeTransaction(self)

    async def execute(self, sql: str, params: Mapping[str, object] | None = None) -> None:
        self.statements.append(sql)


class _FakeTransaction:
    def __init__(self, connection: _FakeSchemaConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> None:
        self._connection.transaction_enters += 1

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self._connection.transaction_exits += 1
        return False
