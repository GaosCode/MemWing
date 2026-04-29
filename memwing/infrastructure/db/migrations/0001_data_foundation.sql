CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS project_memory_spaces (
    id text PRIMARY KEY,
    name text NOT NULL,
    default_safe_mode_enabled boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runtime_scope_bindings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    runtime text NOT NULL,
    agent_id text NOT NULL,
    workspace_id text,
    session_key_pattern text NOT NULL,
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (workspace_id IS NULL OR workspace_id <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_scope_bindings_key
    ON runtime_scope_bindings (
        runtime,
        agent_id,
        COALESCE(workspace_id, ''),
        session_key_pattern
    );

CREATE INDEX IF NOT EXISTS idx_runtime_scope_bindings_project
    ON runtime_scope_bindings (project_memory_space_id);

CREATE TABLE IF NOT EXISTS platform_scope_bindings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    platform text NOT NULL,
    tenant_id text,
    channel_id text NOT NULL,
    thread_id text,
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    group_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (tenant_id IS NULL OR tenant_id <> ''),
    CHECK (thread_id IS NULL OR thread_id <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_scope_bindings_key
    ON platform_scope_bindings (
        platform,
        COALESCE(tenant_id, ''),
        channel_id,
        COALESCE(thread_id, '')
    );

CREATE INDEX IF NOT EXISTS idx_platform_scope_bindings_project_group
    ON platform_scope_bindings (project_memory_space_id, group_id);

CREATE TABLE IF NOT EXISTS group_memory_settings (
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    group_id text NOT NULL,
    safe_mode_enabled boolean NOT NULL,
    shared_group_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_memory_space_id, group_id)
);

CREATE TABLE IF NOT EXISTS source_events (
    id text PRIMARY KEY,
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    group_id text,
    thread_id text,
    shared_group_id text,
    author_id text,
    author_name text,
    source_type text NOT NULL,
    content text NOT NULL,
    content_preview text NOT NULL,
    source_url text,
    event_time timestamptz NOT NULL,
    raw_payload_hash text NOT NULL,
    runtime_event_idempotency_key text,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    purged_at timestamptz,
    purged_by text,
    purge_reason text,
    purge_level text NOT NULL DEFAULT 'none',
    graph_backend_raw_retained boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_memory_space_id, raw_payload_hash)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_events_runtime_idempotency
    ON source_events (project_memory_space_id, runtime_event_idempotency_key)
    WHERE runtime_event_idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_events_scope_time
    ON source_events (project_memory_space_id, group_id, thread_id, event_time);

CREATE INDEX IF NOT EXISTS idx_source_events_purged_at
    ON source_events (purged_at);

CREATE INDEX IF NOT EXISTS idx_source_events_cursor
    ON source_events (project_memory_space_id, event_time, id);

CREATE TABLE IF NOT EXISTS audit_events (
    id text PRIMARY KEY,
    trace_id text NOT NULL,
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    stage text NOT NULL,
    input_ref text,
    output_ref text,
    decision text NOT NULL,
    reason_code text,
    reason_text text,
    source_event_ids text[] NOT NULL DEFAULT '{}',
    latency_ms integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    actor_id text
);

CREATE INDEX IF NOT EXISTS idx_audit_events_trace
    ON audit_events (trace_id);

CREATE INDEX IF NOT EXISTS idx_audit_events_entity_created
    ON audit_events (entity_type, entity_id, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_events_created
    ON audit_events (created_at);

CREATE TABLE IF NOT EXISTS outbox_jobs (
    id text PRIMARY KEY,
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    source_event_id text NOT NULL REFERENCES source_events(id),
    job_type text NOT NULL,
    payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL,
    idempotency_key text NOT NULL,
    aggregate_key text,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    priority integer NOT NULL DEFAULT 100,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    locked_at timestamptz,
    locked_by text,
    lock_expires_at timestamptz,
    last_error text,
    dead_letter_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_outbox_jobs_status_run_priority
    ON outbox_jobs (status, next_run_at, priority);

CREATE INDEX IF NOT EXISTS idx_outbox_jobs_status_lock_expires
    ON outbox_jobs (status, lock_expires_at);

CREATE INDEX IF NOT EXISTS idx_outbox_jobs_project_aggregate_status
    ON outbox_jobs (project_memory_space_id, aggregate_key, status);

CREATE INDEX IF NOT EXISTS idx_outbox_jobs_source_event
    ON outbox_jobs (source_event_id);

CREATE TABLE IF NOT EXISTS evidence_chunks (
    id text PRIMARY KEY,
    source_event_id text NOT NULL REFERENCES source_events(id),
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    group_id text,
    thread_id text,
    shared_group_id text,
    chunk_text text NOT NULL,
    chunk_index integer NOT NULL,
    embedding_model text,
    embedding_ref text,
    embedding_vector double precision[],
    invalidated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_event_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_evidence_chunks_scope
    ON evidence_chunks (project_memory_space_id, group_id, thread_id);

CREATE INDEX IF NOT EXISTS idx_evidence_chunks_invalidated_at
    ON evidence_chunks (invalidated_at);

CREATE TABLE IF NOT EXISTS working_memory_entries (
    id text PRIMARY KEY,
    source_event_id text NOT NULL REFERENCES source_events(id),
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    group_id text,
    thread_id text,
    shared_group_id text,
    content text NOT NULL,
    token_count integer NOT NULL,
    sequence integer NOT NULL,
    flushed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_memory_space_id, thread_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_working_memory_entries_scope_sequence
    ON working_memory_entries (project_memory_space_id, group_id, thread_id, sequence);

CREATE INDEX IF NOT EXISTS idx_working_memory_entries_flushed
    ON working_memory_entries (project_memory_space_id, thread_id, flushed_at);

CREATE TABLE IF NOT EXISTS memory_items (
    id text PRIMARY KEY,
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    group_id text,
    thread_id text,
    shared_group_id text,
    route text NOT NULL,
    display_type text NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    summary text,
    source_event_ids text[] NOT NULL DEFAULT '{}',
    primary_source_event_id text REFERENCES source_events(id),
    status text NOT NULL,
    event_time timestamptz,
    valid_from timestamptz,
    valid_to timestamptz,
    original_score double precision NOT NULL DEFAULT 0,
    half_life_days integer NOT NULL DEFAULT 30,
    last_reviewed_at timestamptz,
    last_confirmed_at timestamptz,
    last_recalled_at timestamptz,
    recall_count integer NOT NULL DEFAULT 0,
    cached_decayed_score double precision,
    last_decay_computed_at timestamptz,
    pinned boolean NOT NULL DEFAULT false,
    created_by text NOT NULL,
    activated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    hidden_at timestamptz,
    invalidated_at timestamptz,
    removed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_memory_items_scope_status
    ON memory_items (project_memory_space_id, group_id, status);

CREATE INDEX IF NOT EXISTS idx_memory_items_project_status_display_updated
    ON memory_items (project_memory_space_id, status, display_type, updated_at);

CREATE INDEX IF NOT EXISTS idx_memory_items_project_group_status_updated
    ON memory_items (project_memory_space_id, group_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_memory_items_review_touch
    ON memory_items (last_reviewed_at, last_confirmed_at);

CREATE TABLE IF NOT EXISTS memory_versions (
    id text PRIMARY KEY,
    memory_id text NOT NULL REFERENCES memory_items(id),
    version integer NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    summary text,
    status text NOT NULL,
    source_event_ids text[] NOT NULL DEFAULT '{}',
    changed_by text NOT NULL,
    change_reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (memory_id, version)
);

CREATE TABLE IF NOT EXISTS memory_pages (
    id text PRIMARY KEY,
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    group_id text,
    thread_id text,
    shared_group_id text,
    scope_type text NOT NULL,
    scope_id text NOT NULL,
    title text NOT NULL,
    brief text NOT NULL,
    topics_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    open_questions text[] NOT NULL DEFAULT '{}',
    next_steps text[] NOT NULL DEFAULT '{}',
    source_event_ids text[] NOT NULL DEFAULT '{}',
    linked_memory_item_ids text[] NOT NULL DEFAULT '{}',
    version integer NOT NULL,
    needs_rebuild boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_memory_space_id, scope_type, scope_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_pages_scope
    ON memory_pages (project_memory_space_id, group_id, thread_id);

CREATE INDEX IF NOT EXISTS idx_memory_pages_needs_rebuild
    ON memory_pages (project_memory_space_id, needs_rebuild, updated_at);

CREATE TABLE IF NOT EXISTS memory_page_versions (
    id text PRIMARY KEY,
    page_id text NOT NULL REFERENCES memory_pages(id),
    version integer NOT NULL,
    title text NOT NULL,
    brief text NOT NULL,
    topics_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    open_questions text[] NOT NULL DEFAULT '{}',
    next_steps text[] NOT NULL DEFAULT '{}',
    source_event_ids text[] NOT NULL DEFAULT '{}',
    linked_memory_item_ids text[] NOT NULL DEFAULT '{}',
    changed_by text NOT NULL,
    change_reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (page_id, version)
);

CREATE TABLE IF NOT EXISTS graph_write_jobs (
    id text PRIMARY KEY,
    backend text NOT NULL,
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    thread_id text,
    saga_id text,
    memory_id text NOT NULL REFERENCES memory_items(id),
    source_event_ids text[] NOT NULL DEFAULT '{}',
    route text NOT NULL,
    status text NOT NULL,
    idempotency_key text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    priority integer NOT NULL DEFAULT 100,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    dead_letter_reason text,
    last_error text,
    locked_at timestamptz,
    locked_by text,
    lock_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_graph_write_jobs_status_lock
    ON graph_write_jobs (status, locked_at);

CREATE INDEX IF NOT EXISTS idx_graph_write_jobs_status_lock_expires
    ON graph_write_jobs (status, lock_expires_at);

CREATE INDEX IF NOT EXISTS idx_graph_write_jobs_status_run_priority
    ON graph_write_jobs (status, next_run_at, priority);

CREATE INDEX IF NOT EXISTS idx_graph_write_jobs_project_thread_saga
    ON graph_write_jobs (project_memory_space_id, thread_id, saga_id);

CREATE INDEX IF NOT EXISTS idx_graph_write_jobs_memory
    ON graph_write_jobs (memory_id);

CREATE TABLE IF NOT EXISTS memory_graph_links (
    id text PRIMARY KEY,
    backend text NOT NULL,
    memory_id text NOT NULL REFERENCES memory_items(id),
    source_event_id text NOT NULL REFERENCES source_events(id),
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    backend_space_id text NOT NULL,
    backend_object_type text NOT NULL,
    backend_object_id text NOT NULL,
    link_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (backend, backend_object_type, backend_object_id, memory_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_memory_graph_links_memory
    ON memory_graph_links (memory_id);

CREATE INDEX IF NOT EXISTS idx_memory_graph_links_source_event
    ON memory_graph_links (source_event_id);

CREATE INDEX IF NOT EXISTS idx_memory_graph_links_project_backend
    ON memory_graph_links (project_memory_space_id, backend);

CREATE TABLE IF NOT EXISTS memory_recall_events (
    id text PRIMARY KEY,
    project_memory_space_id text NOT NULL REFERENCES project_memory_spaces(id),
    memory_id text NOT NULL,
    source text NOT NULL,
    query_hash text NOT NULL,
    trace_id text NOT NULL,
    recalled_at timestamptz NOT NULL,
    rank integer,
    score double precision,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_recall_events_memory_recalled
    ON memory_recall_events (project_memory_space_id, memory_id, recalled_at);

CREATE INDEX IF NOT EXISTS idx_memory_recall_events_trace
    ON memory_recall_events (trace_id);

-- Atomic claim shape for the production Postgres adapter:
-- SELECT id FROM outbox_jobs
-- WHERE (status = 'pending' AND next_run_at <= now())
--    OR (status = 'processing' AND lock_expires_at <= now())
-- ORDER BY status, next_run_at, priority DESC, created_at
-- FOR UPDATE SKIP LOCKED;
