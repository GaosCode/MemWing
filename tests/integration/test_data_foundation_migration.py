from pathlib import Path


def test_data_foundation_migration_declares_required_tables_and_indexes() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "memwing"
        / "infrastructure"
        / "db"
        / "migrations"
        / "0001_data_foundation.sql"
    ).read_text()

    for table in (
        "project_memory_spaces",
        "runtime_scope_bindings",
        "platform_scope_bindings",
        "group_memory_settings",
        "source_events",
        "audit_events",
        "outbox_jobs",
        "memory_items",
        "memory_recall_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration

    assert "UNIQUE (project_memory_space_id, raw_payload_hash)" in migration
    assert "runtime_event_idempotency_key IS NOT NULL" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "UNIQUE (runtime, agent_id, workspace_id, session_key_pattern)" not in migration
    assert "UNIQUE (platform, tenant_id, channel_id, thread_id)" not in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_scope_bindings_key" in migration
    assert "COALESCE(workspace_id, '')" in migration
    assert "CHECK (workspace_id IS NULL OR workspace_id <> '')" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_scope_bindings_key" in migration
    assert "COALESCE(tenant_id, '')" in migration
    assert "COALESCE(thread_id, '')" in migration
    assert "CHECK (tenant_id IS NULL OR tenant_id <> '')" in migration
    assert "CHECK (thread_id IS NULL OR thread_id <> '')" in migration
