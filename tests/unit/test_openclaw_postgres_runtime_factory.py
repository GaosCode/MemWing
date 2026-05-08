import asyncio

import pytest

from memwing.api import runtime_config
from memwing.api.runtime_config import OpenClawRuntimeUnavailableError
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter
from memwing.infrastructure.agents import openclaw_adapter_factory
from memwing.infrastructure.agents.openclaw_adapter_factory import (
    create_openclaw_adapter_from_env,
    create_openclaw_adapter_from_store,
)
from memwing.infrastructure.db.postgres import PostgresDataStore

from tests.unit.postgres_store_fixtures import FakePostgresConnection


def test_factory_builds_openclaw_adapter_from_postgres_store() -> None:
    connection = FakePostgresConnection()

    adapter = create_openclaw_adapter_from_store(PostgresDataStore(connection))

    assert isinstance(adapter, OpenClawAdapter)


def test_runtime_config_requires_database_url_without_in_memory_fallback() -> None:
    with pytest.raises(OpenClawRuntimeUnavailableError, match="DATABASE_URL is required"):
        runtime_config.database_url_from_env({})

    with pytest.raises(OpenClawRuntimeUnavailableError, match="DATABASE_URL is required"):
        runtime_config.database_url_from_env({"DATABASE_URL": "   "})


def test_runtime_config_builds_postgres_openclaw_runtime_from_env(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_create_openclaw_adapter_from_postgres(
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        graph_backend=None,
        evidence_index=None,
        auto_push_enabled: bool = False,
    ):
        captured["database_url"] = database_url
        captured["min_size"] = min_size
        captured["max_size"] = max_size
        captured["graph_backend"] = graph_backend
        captured["evidence_index"] = evidence_index
        captured["auto_push_enabled"] = auto_push_enabled
        return "runtime-handle"

    monkeypatch.setattr(
        openclaw_adapter_factory,
        "create_openclaw_adapter_from_postgres",
        fake_create_openclaw_adapter_from_postgres,
    )

    handle = asyncio.run(
        create_openclaw_adapter_from_env(
            {"DATABASE_URL": " postgresql://memwing@db.invalid/memwing "}
        )
    )

    assert handle == "runtime-handle"
    assert captured == {
        "database_url": "postgresql://memwing@db.invalid/memwing",
        "min_size": 1,
        "max_size": 10,
        "graph_backend": None,
        "evidence_index": None,
        "auto_push_enabled": False,
    }
