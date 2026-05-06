from __future__ import annotations

import asyncio
from multiprocessing import Queue, get_context
from pathlib import Path
import time

from memwing.core.scope import ProjectMemorySpace
from memwing.infrastructure.db.sqlite_store import SQLiteDataStore


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
