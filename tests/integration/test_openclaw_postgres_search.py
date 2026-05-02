import asyncio
from dataclasses import replace

from memwing.api.memwing_tools import memwing_search_memory
from memwing.core.models import MemoryStatus
from memwing.infrastructure.agents.openclaw_adapter_factory import create_openclaw_adapter_from_store
from memwing.infrastructure.db.postgres import PostgresDataStore

from tests.unit.postgres_store_fixtures import (
    FakePostgresConnection,
    memory_item,
    memory_item_row,
    memory_recall_event,
    memory_recall_event_row,
)


def test_memwing_search_memory_reads_from_postgres_backed_openclaw_adapter() -> None:
    now = memory_item().created_at
    memory = replace(
        memory_item(),
        status=MemoryStatus.ACTIVE,
        activated_at=now,
        content="Dashboard migration owner is Mina.",
    )
    connection = FakePostgresConnection(
        fetchrow_results=(
            {
                "id": "project_001",
                "name": "Demo",
                "default_safe_mode_enabled": False,
            },
            {
                "project_memory_space_id": "project_001",
                "group_id": "group_001",
                "safe_mode_enabled": True,
                "shared_group_id": None,
            },
            None,
            memory_recall_event_row(memory_recall_event()),
        ),
        fetch_results=(
            (
                {
                    "runtime": "openclaw",
                    "agent_id": "main",
                    "workspace_id": "workspace_001",
                    "session_key_pattern": "session_001",
                    "project_memory_space_id": "project_001",
                },
            ),
            (),
            (memory_item_row(memory),),
            (),
        ),
    )
    runtime = create_openclaw_adapter_from_store(PostgresDataStore(connection))

    async def scenario() -> None:
        result = await memwing_search_memory(
            {
                "agent_id": "main",
                "workspace_id": "workspace_001",
                "session_id": "session_001",
                "query": "Dashboard migration owner",
                "mode": "current",
                "limit": 5,
                "scope": {
                    "project_memory_space_id": "project_001",
                    "group_id": "group_001",
                    "thread_id": "thread_001",
                },
            },
            runtime,
        )

        assert result.contexts == ("Dashboard migration owner is Mina.",)
        assert result.results[0].id == "memory_001"

    asyncio.run(scenario())

    queries = "\n".join(call[1] for call in connection.calls)
    assert "FROM runtime_scope_bindings" in queries
    assert "FROM memory_items" in queries
    assert "INSERT INTO memory_recall_events" in queries
