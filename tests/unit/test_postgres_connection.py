import asyncio

import pytest
from psycopg.errors import AdminShutdown
from psycopg.types.json import Jsonb

from memwing.core.errors import ProviderTransientFailure
from memwing.infrastructure.db.postgres_connection import (
    PooledPostgresConnection,
    _prepare_params,
    _prepare_sql,
)
from memwing.infrastructure.db.postgres_derived_sql import _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
from memwing.infrastructure.db.postgres_sql import _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL


def test_prepare_sql_escapes_literal_percent_without_changing_placeholders() -> None:
    sql = """
    SELECT *
    FROM runtime_scope_bindings
    WHERE runtime = %(runtime)s
      AND COALESCE(%(session_id)s, '') LIKE replace(session_key_pattern, '%', '!%')
      AND note LIKE %s
      AND raw_payload_hash = %(raw_payload_hash)s
    """

    prepared = _prepare_sql(sql)

    assert "%(runtime)s" in prepared
    assert "%(session_id)s" in prepared
    assert "%(raw_payload_hash)s" in prepared
    assert "LIKE %s" in prepared
    assert "replace(session_key_pattern, '%%', '!%%')" in prepared


def test_prepare_params_wraps_json_columns_without_touching_arrays() -> None:
    prepared = _prepare_params(
        {
            "metadata_json": {"case_id": "bs001"},
            "topics_json": [{"title": "scope"}],
            "source_event_ids": ("source_event_001",),
        }
    )

    assert isinstance(prepared["metadata_json"], Jsonb)
    assert isinstance(prepared["topics_json"], Jsonb)
    assert prepared["source_event_ids"] == ["source_event_001"]


def test_scope_queries_cast_nullable_group_id_arrays() -> None:
    assert "%(group_ids)s::text[] IS NULL" in _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
    assert "ANY(%(group_ids)s::text[])" in _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
    assert "%(thread_id)s::text IS NULL" in _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
    assert "%(shared_group_id)s::text IS NULL" in _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
    assert "%(group_ids)s::text[] IS NULL" in _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL
    assert "ANY(%(group_ids)s::text[])" in _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL
    assert "%(thread_id)s::text IS NULL" in _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL
    assert "%(shared_group_id)s::text IS NULL" in _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL


def test_pooled_connection_retries_transient_disconnect_once() -> None:
    async def run() -> None:
        pool = _FakePool(
            [
                _FakeConnection(execute_error=AdminShutdown("terminating connection")),
                _FakeConnection(rows=({"id": "source_001"},)),
            ]
        )
        connection = PooledPostgresConnection(pool)

        rows = await connection.fetch("SELECT %(id)s", {"id": "source_001"})

        assert rows == ({"id": "source_001"},)
        assert pool.connection_count == 2

    asyncio.run(run())


def test_pooled_connection_maps_repeated_disconnect_to_transient_failure() -> None:
    async def run() -> None:
        pool = _FakePool(
            [
                _FakeConnection(execute_error=AdminShutdown("first disconnect")),
                _FakeConnection(execute_error=AdminShutdown("second disconnect")),
            ]
        )
        connection = PooledPostgresConnection(pool)

        with pytest.raises(ProviderTransientFailure) as exc_info:
            await connection.fetch("SELECT 1", {})

        assert exc_info.value.reason_code == "postgres_unavailable"
        assert pool.connection_count == 2

    asyncio.run(run())


def test_transaction_connection_does_not_retry_transient_disconnect() -> None:
    async def run() -> None:
        connection = PooledPostgresConnection(_FakePool([]))
        transaction_connection = _FakeConnection(
            execute_error=AdminShutdown("transaction disconnect")
        )
        token = connection._current_connection.set(transaction_connection)
        try:
            with pytest.raises(ProviderTransientFailure) as exc_info:
                await connection.fetchrow("SELECT 1", {})
        finally:
            connection._current_connection.reset(token)

        assert exc_info.value.reason_code == "postgres_unavailable"
        assert transaction_connection.execute_count == 1

    asyncio.run(run())


class _FakePool:
    def __init__(self, connections):
        self._connections = list(connections)
        self.connection_count = 0

    def connection(self):
        self.connection_count += 1
        return _FakeConnectionContext(self._connections.pop(0))


class _FakeConnectionContext:
    def __init__(self, connection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeConnection:
    def __init__(self, *, rows=(), row=None, execute_error=None):
        self._rows = rows
        self._row = row
        self._execute_error = execute_error
        self.execute_count = 0

    async def execute(self, sql, params):
        self.execute_count += 1
        if self._execute_error is not None:
            raise self._execute_error
        return _FakeCursor(rows=self._rows, row=self._row)


class _FakeCursor:
    def __init__(self, *, rows, row):
        self._rows = rows
        self._row = row

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._row
