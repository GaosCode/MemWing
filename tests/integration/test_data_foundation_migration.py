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
        "evidence_chunks",
        "working_memory_entries",
        "memory_items",
        "memory_versions",
        "memory_pages",
        "memory_page_versions",
        "graph_write_jobs",
        "memory_graph_links",
        "memory_recall_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration

    assert "UNIQUE (project_memory_space_id, raw_payload_hash)" in migration
    assert "UNIQUE (source_event_id, chunk_index)" in migration
    assert "UNIQUE (memory_id, version)" in migration
    assert "UNIQUE (page_id, version)" in migration
    assert "UNIQUE (idempotency_key)" in migration
    assert (
        "UNIQUE (backend, backend_object_type, backend_object_id, memory_id, link_type)"
        in migration
    )
    assert "runtime_event_idempotency_key IS NOT NULL" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "idx_memory_items_project_status_display_updated" in migration
    assert "idx_memory_items_project_group_status_updated" in migration
    assert "idx_graph_write_jobs_project_thread_saga" in migration
    assert "memory_id text NOT NULL REFERENCES memory_items(id)" in migration
    assert "idx_graph_write_jobs_memory" in migration
    assert "actor_id text" in migration
    assert "idempotency_key text" in migration
    assert "action_ref text" in migration
    assert "lifecycle_revision integer" in migration
    assert "lifecycle_revision integer NOT NULL DEFAULT 0" in migration
    assert "idx_audit_events_entity_idempotency" in migration
    assert "idx_memory_pages_needs_rebuild" in migration
    assert "topics_json jsonb NOT NULL DEFAULT '[]'::jsonb" in migration
    assert "open_questions text[] NOT NULL DEFAULT '{}'" in migration
    assert "next_steps text[] NOT NULL DEFAULT '{}'" in migration
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
