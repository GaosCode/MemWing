from __future__ import annotations

from typing import Any
import os

from memwing.core.scope import ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.sqlite_store import SQLiteDataStore


async def ensure_lite_scope(store: SQLiteDataStore) -> None:
    project_id = default_project_from_env()
    workspace_id = openclaw_workspace_from_env()
    async with store.transaction() as transaction:
        if transaction.state.projects.get(project_id) is None:
            transaction.state.projects[project_id] = ProjectMemorySpace(
                id=project_id,
                name=project_id,
                default_safe_mode_enabled=False,
            )
        binding = RuntimeScopeBinding(
            runtime="openclaw",
            agent_id="main",
            workspace_id=workspace_id,
            session_key_pattern="*",
            project_memory_space_id=project_id,
        )
        if binding not in transaction.state.runtime_bindings:
            transaction.state.runtime_bindings.append(binding)


async def ensure_postgres_scope(connection: Any) -> None:
    project_id = default_project_from_env()
    workspace_id = openclaw_workspace_from_env()
    await connection.execute(
        """
        INSERT INTO project_memory_spaces (id, name, default_safe_mode_enabled)
        VALUES (%(project_id)s, %(project_id)s, false)
        ON CONFLICT (id) DO NOTHING
        """,
        {"project_id": project_id},
    )
    binding_params = {
        "runtime": "openclaw",
        "agent_id": "main",
        "workspace_id": workspace_id,
        "session_key_pattern": "*",
        "project_id": project_id,
    }
    await connection.execute(
        """
        UPDATE runtime_scope_bindings
        SET project_memory_space_id = %(project_id)s,
            updated_at = now()
        WHERE runtime = %(runtime)s
          AND agent_id = %(agent_id)s
          AND workspace_id IS NOT DISTINCT FROM %(workspace_id)s
          AND session_key_pattern = %(session_key_pattern)s
        """,
        binding_params,
    )
    await connection.execute(
        """
        INSERT INTO runtime_scope_bindings (
            runtime,
            agent_id,
            workspace_id,
            session_key_pattern,
            project_memory_space_id
        )
        SELECT
            %(runtime)s,
            %(agent_id)s,
            %(workspace_id)s,
            %(session_key_pattern)s,
            %(project_id)s
        WHERE NOT EXISTS (
            SELECT 1
            FROM runtime_scope_bindings
            WHERE runtime = %(runtime)s
              AND agent_id = %(agent_id)s
              AND workspace_id IS NOT DISTINCT FROM %(workspace_id)s
              AND session_key_pattern = %(session_key_pattern)s
        )
        """,
        binding_params,
    )


def default_project_from_env() -> str:
    return os.environ.get("MEMWING_DEFAULT_PROJECT_MEMORY_SPACE_ID", "").strip() or "project_001"


def openclaw_workspace_from_env() -> str:
    return os.environ.get("MEMWING_OPENCLAW_WORKSPACE_ID", "").strip() or "workspace_001"
