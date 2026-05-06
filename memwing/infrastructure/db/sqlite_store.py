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
            row = connection.execute(
                "SELECT payload FROM memwing_state WHERE key = ?",
                (_STATE_KEY,),
            ).fetchone()
        if row is None:
            self._state = InMemoryState()
            return
        self._state = pickle.loads(row[0])

    def _write_state(self) -> None:
        payload = pickle.dumps(self._state)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO memwing_state (key, payload)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET payload = excluded.payload
                """,
                (_STATE_KEY, payload),
            )
            connection.commit()


class _SQLiteTransaction(_Transaction):
    def __init__(self, store: SQLiteDataStore) -> None:
        super().__init__(store)
        self._sqlite_store = store

    async def __aenter__(self) -> _SQLiteTransaction:
        await self._sqlite_store._lock.acquire()
        async with self._sqlite_store._file_lock:
            self._sqlite_store._load_state()
        self._state = pickle.loads(pickle.dumps(self._sqlite_store._state))
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            if exc_type is None:
                self._sqlite_store._state = self._state
                async with self._sqlite_store._file_lock:
                    self._sqlite_store._write_state()
        finally:
            self._sqlite_store._lock.release()
        return False
