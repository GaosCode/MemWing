from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from contextvars import ContextVar, Token
import re
from types import TracebackType
from typing import Any, Awaitable, Callable, TypeVar

from memwing.core.errors import ProviderTransientFailure
from memwing.infrastructure.db.postgres_rows import Row


class PooledPostgresConnection:
    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._current_connection: ContextVar[Any | None] = ContextVar(
            "memwing_postgres_connection",
            default=None,
        )

    @classmethod
    async def connect(
        cls,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
    ) -> PooledPostgresConnection:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        await pool.open(wait=True)
        return cls(pool)

    def transaction(self) -> AbstractAsyncContextManager[object]:
        return _PooledTransaction(self._pool, self._current_connection)

    async def fetchrow(self, sql: str, params: dict[str, object]) -> Row | None:
        connection = self._current_connection.get()
        if connection is not None:
            return await _run_transaction_operation(_fetchrow, connection, sql, params)
        return await _run_pool_operation_with_retry(self._pool, _fetchrow, sql, params)

    async def fetch(self, sql: str, params: dict[str, object]) -> tuple[Row, ...]:
        connection = self._current_connection.get()
        if connection is not None:
            return await _run_transaction_operation(_fetch, connection, sql, params)
        return await _run_pool_operation_with_retry(self._pool, _fetch, sql, params)

    async def execute(self, sql: str, params: dict[str, object] | None = None) -> None:
        prepared_params = params or {}
        connection = self._current_connection.get()
        if connection is not None:
            return await _run_transaction_operation(_execute, connection, sql, prepared_params)
        return await _run_pool_operation_with_retry(self._pool, _execute, sql, prepared_params)

    async def close(self) -> None:
        await self._pool.close()


class _PooledTransaction:
    def __init__(self, pool: Any, current_connection: ContextVar[Any | None]) -> None:
        self._pool = pool
        self._current_connection = current_connection
        self._connection_context: AbstractAsyncContextManager[Any] | None = None
        self._transaction_context: AbstractAsyncContextManager[Any] | None = None
        self._connection: Any | None = None
        self._token: Token[Any] | None = None

    async def __aenter__(self) -> _PooledTransaction:
        self._connection_context = self._pool.connection()
        self._connection = await self._connection_context.__aenter__()
        self._transaction_context = self._connection.transaction()
        await self._transaction_context.__aenter__()
        self._token = self._current_connection.set(self._connection)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        suppress = False
        try:
            if self._transaction_context is not None:
                suppress = await self._transaction_context.__aexit__(exc_type, exc, traceback)
        finally:
            if self._token is not None:
                self._current_connection.reset(self._token)
            if self._connection_context is not None:
                await self._connection_context.__aexit__(exc_type, exc, traceback)
        return suppress


async def _fetchrow(connection: Any, sql: str, params: dict[str, object]) -> Row | None:
    cursor = await connection.execute(_prepare_sql(sql), _prepare_params(params))
    return await cursor.fetchone()


async def _fetch(connection: Any, sql: str, params: dict[str, object]) -> tuple[Row, ...]:
    cursor = await connection.execute(_prepare_sql(sql), _prepare_params(params))
    return tuple(await cursor.fetchall())


async def _execute(connection: Any, sql: str, params: dict[str, object]) -> None:
    await connection.execute(_prepare_sql(sql), _prepare_params(params))


T = TypeVar("T")
DatabaseOperation = Callable[[Any, str, dict[str, object]], Awaitable[T]]


async def _run_pool_operation_with_retry(
    pool: Any,
    operation: DatabaseOperation[T],
    sql: str,
    params: dict[str, object],
) -> T:
    try:
        async with pool.connection() as connection:
            return await operation(connection, sql, params)
    except Exception as exc:
        if not _is_transient_postgres_disconnect(exc):
            raise

    try:
        async with pool.connection() as connection:
            return await operation(connection, sql, params)
    except Exception as exc:
        if _is_transient_postgres_disconnect(exc):
            raise _postgres_transient_failure() from exc
        raise


async def _run_transaction_operation(
    operation: DatabaseOperation[T],
    connection: Any,
    sql: str,
    params: dict[str, object],
) -> T:
    try:
        return await operation(connection, sql, params)
    except Exception as exc:
        if _is_transient_postgres_disconnect(exc):
            raise _postgres_transient_failure() from exc
        raise


def _is_transient_postgres_disconnect(exc: BaseException) -> bool:
    try:
        from psycopg import OperationalError
        from psycopg.errors import AdminShutdown, CannotConnectNow, ConnectionException
    except ImportError:
        return False
    return isinstance(
        exc,
        (
            AdminShutdown,
            CannotConnectNow,
            ConnectionException,
            OperationalError,
        ),
    )


def _postgres_transient_failure() -> ProviderTransientFailure:
    return ProviderTransientFailure(
        "postgres_unavailable",
        "Postgres is temporarily unavailable.",
    )


_PSYCOPG_LITERAL_PERCENT = re.compile(r"%(?!\(|s|b|t|%)")


def _prepare_sql(sql: str) -> str:
    return _PSYCOPG_LITERAL_PERCENT.sub("%%", sql)


def _prepare_params(params: dict[str, object]) -> dict[str, object]:
    from psycopg.types.json import Jsonb

    return {key: _prepare_param_value(key, value, Jsonb) for key, value in params.items()}


def _prepare_param_value(key: str, value: object, jsonb_type: type[Any]) -> object:
    if key.endswith("_json") and value is not None:
        return jsonb_type(value)
    if isinstance(value, tuple):
        return list(value)
    return value


__all__ = ("PooledPostgresConnection",)
