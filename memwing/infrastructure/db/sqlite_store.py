from __future__ import annotations

import asyncio
import pickle
from pathlib import Path
import sqlite3
from typing import Final

from memwing.infrastructure.db.in_memory import InMemoryDataStore, _Transaction
from memwing.infrastructure.db.in_memory_state import InMemoryState


_STATE_KEY: Final = "default"


class SQLiteDataStore(InMemoryDataStore):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self._file_lock = asyncio.Lock()
        self._ensure_database()
        self._load_state()

    @classmethod
    def from_path(cls, path: str | Path) -> SQLiteDataStore:
        return cls(Path(path).expanduser())

    async def flush(self) -> None:
        async with self._file_lock:
            self._write_state()

    def transaction(self) -> _SQLiteTransaction:
        return _SQLiteTransaction(self)

    def _ensure_database(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memwing_state (
                    key TEXT PRIMARY KEY,
                    payload BLOB NOT NULL
                )
                """
            )
            connection.commit()

    def _load_state(self) -> None:
        with sqlite3.connect(self.path) as connection:
            self._load_state_from_connection(connection)

    def _load_state_from_connection(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT payload FROM memwing_state WHERE key = ?",
            (_STATE_KEY,),
        ).fetchone()
        if row is None:
            self._state = InMemoryState()
            return
        self._state = pickle.loads(row[0])

    def _write_state(self) -> None:
        with sqlite3.connect(self.path) as connection:
            self._write_state_to_connection(connection)
            connection.commit()

    def _write_state_to_connection(self, connection: sqlite3.Connection) -> None:
        payload = pickle.dumps(self._state)
        connection.execute(
            """
            INSERT INTO memwing_state (key, payload)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET payload = excluded.payload
            """,
            (_STATE_KEY, payload),
        )


class _SQLiteTransaction(_Transaction):
    def __init__(self, store: SQLiteDataStore) -> None:
        super().__init__(store)
        self._sqlite_store = store
        self._connection: sqlite3.Connection | None = None

    async def __aenter__(self) -> _SQLiteTransaction:
        await self._sqlite_store._lock.acquire()
        connection = sqlite3.connect(self._sqlite_store.path, timeout=30, isolation_level=None)
        connection.execute("BEGIN IMMEDIATE")
        self._connection = connection
        self._sqlite_store._load_state_from_connection(connection)
        self._state = pickle.loads(pickle.dumps(self._sqlite_store._state))
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        connection = self._connection
        try:
            if exc_type is None and connection is not None:
                self._sqlite_store._state = self._state
                self._sqlite_store._write_state_to_connection(connection)
                connection.commit()
            elif connection is not None:
                connection.rollback()
        finally:
            if connection is not None:
                connection.close()
            self._connection = None
            self._sqlite_store._lock.release()
        return False
