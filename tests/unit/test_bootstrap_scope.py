import asyncio

from memwing.bootstrap_scope import ensure_postgres_scope


def test_ensure_postgres_scope_seeds_default_openclaw_binding(monkeypatch) -> None:
    monkeypatch.setenv("MEMWING_DEFAULT_PROJECT_MEMORY_SPACE_ID", "demo_scope")
    monkeypatch.setenv("MEMWING_OPENCLAW_WORKSPACE_ID", "workspace_demo")
    connection = _FakeConnection()

    asyncio.run(ensure_postgres_scope(connection))

    assert len(connection.executions) == 3
    assert connection.executions[0][1] == {"project_id": "demo_scope"}
    assert connection.executions[1][1] == {
        "runtime": "openclaw",
        "agent_id": "main",
        "workspace_id": "workspace_demo",
        "session_key_pattern": "*",
        "project_id": "demo_scope",
    }
    assert connection.executions[2][1] == connection.executions[1][1]
    assert "INSERT INTO project_memory_spaces" in connection.executions[0][0]
    assert "UPDATE runtime_scope_bindings" in connection.executions[1][0]
    assert "INSERT INTO runtime_scope_bindings" in connection.executions[2][0]


class _FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, dict[str, object]]] = []

    async def execute(self, sql: str, params: dict[str, object] | None = None) -> None:
        self.executions.append((sql, params or {}))
