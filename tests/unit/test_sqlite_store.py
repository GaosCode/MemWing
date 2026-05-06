from __future__ import annotations

import asyncio
from multiprocessing import Queue, get_context
from pathlib import Path
import json
import sqlite3
import time

import pytest

from memwing.core.scope import ProjectMemorySpace
from memwing.infrastructure.db.sqlite_store import SQLiteDataStore, SQLiteStoreError


def test_sqlite_store_serializes_read_modify_write_transactions_across_processes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memwing.db"
    context = get_context("spawn")
    queue: Queue[str] = context.Queue()
    first = context.Process(
        target=_write_project_in_process,
        args=(db_path, "project_first", 0.4, queue),
    )
    second = context.Process(
        target=_write_project_in_process,
        args=(db_path, "project_second", 0, queue),
    )

    first.start()
    time.sleep(0.1)
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert sorted((queue.get(timeout=1), queue.get(timeout=1))) == [
        "project_first",
        "project_second",
    ]
    store = SQLiteDataStore.from_path(db_path)
    assert sorted(project.id for project in store._state.projects.values()) == [
        "project_first",
        "project_second",
    ]


def test_sqlite_store_persists_versioned_json_state(tmp_path: Path) -> None:
    db_path = tmp_path / "memwing.db"
    store = SQLiteDataStore.from_path(db_path)
    store.add_project_memory_space(
        ProjectMemorySpace(id="project_json", name="Project JSON", default_safe_mode_enabled=False)
    )
    asyncio.run(store.flush())

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT schema_version, payload FROM memwing_state WHERE key = 'default'"
        ).fetchone()

    assert row is not None
    schema_version, payload = row
    assert schema_version == 1
    assert isinstance(payload, str)
    decoded = json.loads(payload)
    assert decoded["schema_version"] == 1
    assert decoded["state"]["projects"]["project_json"]["fields"]["id"] == "project_json"


def test_sqlite_store_rejects_legacy_pickle_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "memwing.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE memwing_state (
                key TEXT PRIMARY KEY,
                payload BLOB NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO memwing_state (key, payload) VALUES ('default', ?)",
            (b"\x80\x04legacy-pickle",),
        )

    with pytest.raises(SQLiteStoreError, match="legacy pickle"):
        SQLiteDataStore.from_path(db_path)


def _write_project_in_process(
    db_path: Path,
    project_id: str,
    sleep_seconds: float,
    queue: Queue[str],
) -> None:
    async def run() -> None:
        store = SQLiteDataStore.from_path(db_path)
        async with store.transaction() as transaction:
            transaction.state.projects[project_id] = ProjectMemorySpace(
                id=project_id,
                name=project_id,
                default_safe_mode_enabled=False,
            )
            if sleep_seconds:
                time.sleep(sleep_seconds)
        queue.put(project_id)

    asyncio.run(run())
