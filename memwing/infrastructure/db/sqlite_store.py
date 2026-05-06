from __future__ import annotations

import asyncio
import copy
from dataclasses import fields, is_dataclass
from datetime import datetime
import importlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from typing import Final

from memwing.infrastructure.db.in_memory import InMemoryDataStore, _Transaction
from memwing.infrastructure.db.in_memory_state import InMemoryState


_STATE_KEY: Final = "default"
_SCHEMA_VERSION: Final = 1


class SQLiteStoreError(ValueError):
    pass


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
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    payload TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(memwing_state)").fetchall()
            }
            if "schema_version" not in columns:
                connection.execute(
                    "ALTER TABLE memwing_state ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 0"
                )
            connection.commit()

    def _load_state(self) -> None:
        with sqlite3.connect(self.path) as connection:
            self._load_state_from_connection(connection)

    def _load_state_from_connection(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT schema_version, payload FROM memwing_state WHERE key = ?",
            (_STATE_KEY,),
        ).fetchone()
        if row is None:
            self._state = InMemoryState()
            return
        schema_version, payload = row
        if schema_version != _SCHEMA_VERSION:
            raise SQLiteStoreError(
                "Lite SQLite store contains unsupported legacy pickle state; "
                "export with the previous version before opening it here."
            )
        if isinstance(payload, bytes):
            raise SQLiteStoreError("Lite SQLite store contains legacy pickle state.")
        self._state = _decode_state(payload)

    def _write_state(self) -> None:
        with sqlite3.connect(self.path) as connection:
            self._write_state_to_connection(connection)
            connection.commit()

    def _write_state_to_connection(self, connection: sqlite3.Connection) -> None:
        payload = _encode_state(self._state)
        connection.execute(
            """
            INSERT INTO memwing_state (key, schema_version, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                schema_version = excluded.schema_version,
                payload = excluded.payload
            """,
            (_STATE_KEY, _SCHEMA_VERSION, payload),
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
        self._state = copy.deepcopy(self._sqlite_store._state)
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


def _encode_state(state: InMemoryState) -> str:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "state": _encode_dataclass_fields(state),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode_state(payload: str) -> InMemoryState:
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SQLiteStoreError("Lite SQLite state payload is not valid JSON.") from exc
    if not isinstance(decoded, dict) or decoded.get("schema_version") != _SCHEMA_VERSION:
        raise SQLiteStoreError("Lite SQLite state payload has an unsupported schema version.")
    state_payload = decoded.get("state")
    if not isinstance(state_payload, dict):
        raise SQLiteStoreError("Lite SQLite state payload is missing state.")
    return InMemoryState(**{
        field.name: _decode_value(state_payload.get(field.name))
        for field in fields(InMemoryState)
        if field.name in state_payload
    })


def _encode_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
            "fields": _encode_dataclass_fields(value),
        }
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, tuple):
        return {"__tuple__": [_encode_value(item) for item in value]}
    if isinstance(value, list):
        return [_encode_value(item) for item in value]
    if isinstance(value, dict):
        if all(isinstance(key, str) for key in value):
            return {key: _encode_value(item) for key, item in value.items()}
        return {
            "__mapping__": [
                [_encode_value(key), _encode_value(item)]
                for key, item in value.items()
            ]
        }
    return value


def _encode_dataclass_fields(value: object) -> dict[str, Any]:
    return {
        field.name: _encode_value(getattr(value, field.name))
        for field in fields(value)
    }


def _decode_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "__datetime__" in value:
        return datetime.fromisoformat(_required_text(value["__datetime__"]))
    if "__tuple__" in value:
        raw_items = value["__tuple__"]
        if not isinstance(raw_items, list):
            raise SQLiteStoreError("Lite SQLite tuple payload must be a list.")
        return tuple(_decode_value(item) for item in raw_items)
    if "__mapping__" in value:
        raw_items = value["__mapping__"]
        if not isinstance(raw_items, list):
            raise SQLiteStoreError("Lite SQLite mapping payload must be a list.")
        decoded: dict[object, object] = {}
        for pair in raw_items:
            if not isinstance(pair, list) or len(pair) != 2:
                raise SQLiteStoreError("Lite SQLite mapping entries must be key/value pairs.")
            decoded[_decode_value(pair[0])] = _decode_value(pair[1])
        return decoded
    if "__dataclass__" in value:
        class_path = _required_text(value["__dataclass__"])
        raw_fields = value.get("fields")
        if not isinstance(raw_fields, dict):
            raise SQLiteStoreError("Lite SQLite dataclass payload is missing fields.")
        cls = _allowed_dataclass(class_path)
        return cls(**{name: _decode_value(item) for name, item in raw_fields.items()})
    return {key: _decode_value(item) for key, item in value.items()}


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SQLiteStoreError("Lite SQLite payload expected text.")
    return value


def _allowed_dataclass(class_path: str) -> type:
    module_name, _, class_name = class_path.rpartition(".")
    if module_name not in {
        "memwing.core.models",
        "memwing.core.scope",
        "memwing.ports.model_result_cache",
    }:
        raise SQLiteStoreError(f"Lite SQLite dataclass is not allowed: {class_path}")
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)
    if cls is None or not is_dataclass(cls):
        raise SQLiteStoreError(f"Lite SQLite dataclass is not supported: {class_path}")
    return cls
