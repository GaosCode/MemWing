_UPSERT_EVIDENCE_CHUNK_SQL = """
INSERT INTO evidence_chunks (
    id, source_event_id, project_memory_space_id, group_id, thread_id, shared_group_id,
    chunk_text, chunk_index, embedding_model, embedding_ref, embedding_vector,
    invalidated_at, created_at
) VALUES (
    %(id)s, %(source_event_id)s, %(project_memory_space_id)s, %(group_id)s,
    %(thread_id)s, %(shared_group_id)s, %(chunk_text)s, %(chunk_index)s,
    %(embedding_model)s, %(embedding_ref)s, %(embedding_vector)s,
    %(invalidated_at)s, %(created_at)s
)
ON CONFLICT (source_event_id, chunk_index) DO UPDATE
SET project_memory_space_id = EXCLUDED.project_memory_space_id,
    group_id = EXCLUDED.group_id,
    thread_id = EXCLUDED.thread_id,
    shared_group_id = EXCLUDED.shared_group_id,
    chunk_text = EXCLUDED.chunk_text,
    embedding_model = EXCLUDED.embedding_model,
    embedding_ref = EXCLUDED.embedding_ref,
    embedding_vector = EXCLUDED.embedding_vector,
    invalidated_at = EXCLUDED.invalidated_at
RETURNING *
"""

_MARK_EVIDENCE_SOURCE_REDACTED_SQL = """
UPDATE evidence_chunks
SET invalidated_at = %(invalidated_at)s
WHERE source_event_id = %(source_event_id)s
  AND invalidated_at IS NULL
RETURNING id
"""

_APPEND_WORKING_MEMORY_SQL = """
INSERT INTO working_memory_entries (
    id, source_event_id, project_memory_space_id, group_id, thread_id, shared_group_id,
    content, token_count, sequence, flushed_at, created_at
) VALUES (
    %(id)s, %(source_event_id)s, %(project_memory_space_id)s, %(group_id)s,
    %(thread_id)s, %(shared_group_id)s, %(content)s, %(token_count)s,
    %(sequence)s, %(flushed_at)s, %(created_at)s
)
ON CONFLICT (project_memory_space_id, thread_id, sequence) DO NOTHING
RETURNING *
"""

_LIST_RECENT_WORKING_MEMORY_SQL = """
SELECT *
FROM working_memory_entries
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND thread_id IS NOT DISTINCT FROM %(thread_id)s
  AND flushed_at IS NULL
ORDER BY sequence DESC
LIMIT %(limit)s
"""

_NEXT_WORKING_MEMORY_SEQUENCE_SQL = """
SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
FROM working_memory_entries
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND thread_id IS NOT DISTINCT FROM %(thread_id)s
"""

_SUM_UNFLUSHED_WORKING_MEMORY_TOKENS_SQL = """
SELECT COALESCE(SUM(token_count), 0) AS token_count
FROM working_memory_entries
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND group_id IS NOT DISTINCT FROM %(group_id)s
  AND thread_id IS NOT DISTINCT FROM %(thread_id)s
  AND flushed_at IS NULL
"""

_MARK_WORKING_MEMORY_FLUSHED_SQL = """
UPDATE working_memory_entries
SET flushed_at = %(flushed_at)s
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND thread_id IS NOT DISTINCT FROM %(thread_id)s
  AND sequence <= %(through_sequence)s
  AND flushed_at IS NULL
RETURNING id
"""

_UPSERT_MEMORY_ITEM_SQL = """
INSERT INTO memory_items (
    id, project_memory_space_id, group_id, thread_id, shared_group_id, route,
    display_type, title, content, summary, source_event_ids, primary_source_event_id,
    status, event_time, valid_from, valid_to, original_score, half_life_days,
    last_reviewed_at, last_confirmed_at, last_recalled_at, recall_count,
    cached_decayed_score, last_decay_computed_at, pinned, created_by, activated_at,
    created_at, updated_at, archived_at, hidden_at, invalidated_at, removed_at,
    lifecycle_revision
) VALUES (
    %(id)s, %(project_memory_space_id)s, %(group_id)s, %(thread_id)s,
    %(shared_group_id)s, %(route)s, %(display_type)s, %(title)s, %(content)s,
    %(summary)s, %(source_event_ids)s, %(primary_source_event_id)s, %(status)s,
    %(event_time)s, %(valid_from)s, %(valid_to)s, %(original_score)s,
    %(half_life_days)s, %(last_reviewed_at)s, %(last_confirmed_at)s,
    %(last_recalled_at)s, %(recall_count)s, %(cached_decayed_score)s,
    %(last_decay_computed_at)s, %(pinned)s, %(created_by)s, %(activated_at)s,
    %(created_at)s, %(updated_at)s, %(archived_at)s, %(hidden_at)s,
    %(invalidated_at)s, %(removed_at)s, %(lifecycle_revision)s
)
ON CONFLICT (id) DO UPDATE
SET project_memory_space_id = EXCLUDED.project_memory_space_id,
    group_id = EXCLUDED.group_id,
    thread_id = EXCLUDED.thread_id,
    shared_group_id = EXCLUDED.shared_group_id,
    route = EXCLUDED.route,
    display_type = EXCLUDED.display_type,
    title = EXCLUDED.title,
    content = EXCLUDED.content,
    summary = EXCLUDED.summary,
    source_event_ids = EXCLUDED.source_event_ids,
    primary_source_event_id = EXCLUDED.primary_source_event_id,
    status = EXCLUDED.status,
    event_time = EXCLUDED.event_time,
    valid_from = EXCLUDED.valid_from,
    valid_to = EXCLUDED.valid_to,
    original_score = EXCLUDED.original_score,
    half_life_days = EXCLUDED.half_life_days,
    last_reviewed_at = EXCLUDED.last_reviewed_at,
    last_confirmed_at = EXCLUDED.last_confirmed_at,
    last_recalled_at = EXCLUDED.last_recalled_at,
    recall_count = EXCLUDED.recall_count,
    cached_decayed_score = EXCLUDED.cached_decayed_score,
    last_decay_computed_at = EXCLUDED.last_decay_computed_at,
    pinned = EXCLUDED.pinned,
    created_by = EXCLUDED.created_by,
    activated_at = EXCLUDED.activated_at,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at,
    archived_at = EXCLUDED.archived_at,
    hidden_at = EXCLUDED.hidden_at,
    invalidated_at = EXCLUDED.invalidated_at,
    removed_at = EXCLUDED.removed_at,
    lifecycle_revision = EXCLUDED.lifecycle_revision
RETURNING *
"""

_GET_MEMORY_ITEM_SQL = "SELECT * FROM memory_items WHERE id = %(memory_id)s"

_GET_MEMORY_ITEM_FOR_UPDATE_SQL = """
SELECT *
FROM memory_items
WHERE id = %(memory_id)s
FOR UPDATE
"""

_LIST_MEMORY_ITEMS_BY_SOURCE_SQL = """
SELECT *
FROM memory_items
WHERE %(source_event_id)s = ANY(source_event_ids)
ORDER BY updated_at DESC, id
"""

_LIST_MEMORY_ITEMS_FOR_SCOPE_SQL = """
SELECT *
FROM memory_items
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND (%(group_ids)s IS NULL OR group_id = ANY(%(group_ids)s))
  AND (%(thread_id)s IS NULL OR thread_id IS NOT DISTINCT FROM %(thread_id)s)
  AND (
      %(shared_group_id)s IS NULL
      OR shared_group_id IS NOT DISTINCT FROM %(shared_group_id)s
  )
ORDER BY updated_at DESC, id
LIMIT %(limit)s
"""

_INSERT_MEMORY_VERSION_SQL = """
INSERT INTO memory_versions (
    id, memory_id, version, title, content, summary, status, source_event_ids,
    changed_by, change_reason, created_at
) VALUES (
    %(id)s, %(memory_id)s, %(version)s, %(title)s, %(content)s, %(summary)s,
    %(status)s, %(source_event_ids)s, %(changed_by)s, %(change_reason)s,
    %(created_at)s
)
ON CONFLICT (memory_id, version) DO NOTHING
RETURNING *
"""

_GET_LATEST_MEMORY_VERSION_SQL = """
SELECT *
FROM memory_versions
WHERE memory_id = %(memory_id)s
ORDER BY version DESC
LIMIT 1
"""

_UPSERT_MEMORY_PAGE_SQL = """
INSERT INTO memory_pages (
    id, project_memory_space_id, group_id, thread_id, shared_group_id, scope_type,
    scope_id, title, brief, topics_json, open_questions, next_steps, source_event_ids,
    linked_memory_item_ids, version, needs_rebuild, created_at, updated_at
) VALUES (
    %(id)s, %(project_memory_space_id)s, %(group_id)s, %(thread_id)s,
    %(shared_group_id)s, %(scope_type)s, %(scope_id)s, %(title)s, %(brief)s,
    %(topics_json)s, %(open_questions)s, %(next_steps)s, %(source_event_ids)s,
    %(linked_memory_item_ids)s, %(version)s, %(needs_rebuild)s, %(created_at)s,
    %(updated_at)s
)
ON CONFLICT (project_memory_space_id, scope_type, scope_id) DO UPDATE
SET group_id = EXCLUDED.group_id,
    thread_id = EXCLUDED.thread_id,
    shared_group_id = EXCLUDED.shared_group_id,
    title = EXCLUDED.title,
    brief = EXCLUDED.brief,
    topics_json = EXCLUDED.topics_json,
    open_questions = EXCLUDED.open_questions,
    next_steps = EXCLUDED.next_steps,
    source_event_ids = EXCLUDED.source_event_ids,
    linked_memory_item_ids = EXCLUDED.linked_memory_item_ids,
    version = EXCLUDED.version,
    needs_rebuild = EXCLUDED.needs_rebuild,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at
RETURNING *
"""

_GET_MEMORY_PAGE_BY_SCOPE_SQL = """
SELECT *
FROM memory_pages
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND scope_type = %(scope_type)s
  AND scope_id = %(scope_id)s
"""

_LOCK_MEMORY_PAGE_SCOPE_SQL = """
SELECT pg_advisory_xact_lock(
    hashtextextended(
        %(project_memory_space_id)s || ':' || %(scope_type)s || ':' || %(scope_id)s,
        0
    )
)
"""

_GET_MEMORY_PAGE_BY_SCOPE_FOR_UPDATE_SQL = """
SELECT *
FROM memory_pages
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND scope_type = %(scope_type)s
  AND scope_id = %(scope_id)s
FOR UPDATE
"""

_MARK_MEMORY_PAGES_REBUILD_FOR_SOURCE_SQL = """
UPDATE memory_pages
SET needs_rebuild = true,
    updated_at = %(updated_at)s
WHERE %(source_event_id)s = ANY(source_event_ids)
  AND needs_rebuild = false
RETURNING id
"""

_LIST_MEMORY_PAGES_NEEDS_REBUILD_SQL = """
SELECT *
FROM memory_pages
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND needs_rebuild = true
ORDER BY updated_at ASC, id
LIMIT %(limit)s
"""

_INSERT_MEMORY_PAGE_VERSION_SQL = """
INSERT INTO memory_page_versions (
    id, page_id, version, title, brief, topics_json, open_questions, next_steps,
    source_event_ids, linked_memory_item_ids, changed_by, change_reason, created_at
) VALUES (
    %(id)s, %(page_id)s, %(version)s, %(title)s, %(brief)s,
    %(topics_json)s, %(open_questions)s, %(next_steps)s, %(source_event_ids)s,
    %(linked_memory_item_ids)s, %(changed_by)s, %(change_reason)s, %(created_at)s
)
ON CONFLICT (page_id, version) DO NOTHING
RETURNING *
"""

_INSERT_GRAPH_WRITE_JOB_SQL = """
INSERT INTO graph_write_jobs (
    id, backend, project_memory_space_id, thread_id, saga_id, memory_id, source_event_ids,
    route, status, idempotency_key, attempts, max_attempts, priority, next_run_at,
    dead_letter_reason, last_error, locked_at, locked_by, lock_expires_at,
    created_at, updated_at
) VALUES (
    %(id)s, %(backend)s, %(project_memory_space_id)s, %(thread_id)s,
    %(saga_id)s, %(memory_id)s, %(source_event_ids)s, %(route)s, %(status)s,
    %(idempotency_key)s, %(attempts)s, %(max_attempts)s, %(priority)s,
    %(next_run_at)s, %(dead_letter_reason)s, %(last_error)s, %(locked_at)s,
    %(locked_by)s, %(lock_expires_at)s, %(created_at)s, %(updated_at)s
)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING *
"""

_CLAIM_GRAPH_WRITE_JOBS_SQL = """
WITH candidates AS (
    SELECT
        job.id,
        job.status,
        job.next_run_at,
        job.priority,
        job.created_at,
        ROW_NUMBER() OVER (
            PARTITION BY job.project_memory_space_id
            ORDER BY
                CASE WHEN job.status = 'pending' THEN 0 ELSE 1 END,
                job.next_run_at,
                job.priority DESC,
                job.created_at
        ) AS project_rank,
        ROW_NUMBER() OVER (
            PARTITION BY job.project_memory_space_id, job.thread_id, job.saga_id
            ORDER BY
                CASE WHEN job.status = 'pending' THEN 0 ELSE 1 END,
                job.next_run_at,
                job.priority DESC,
                job.created_at
        ) AS group_rank
    FROM graph_write_jobs AS job
    WHERE (
            (job.status = 'pending' AND job.next_run_at <= %(now)s)
         OR (job.status = 'processing' AND job.lock_expires_at <= %(now)s)
        )
      AND NOT EXISTS (
          SELECT 1
          FROM graph_write_jobs AS active
          WHERE active.project_memory_space_id = job.project_memory_space_id
            AND active.thread_id IS NOT DISTINCT FROM job.thread_id
            AND active.saga_id IS NOT DISTINCT FROM job.saga_id
            AND active.status = 'processing'
            AND (active.lock_expires_at IS NULL OR active.lock_expires_at > %(now)s)
      )
      AND NOT EXISTS (
          SELECT 1
          FROM graph_write_jobs AS project_active
          WHERE project_active.project_memory_space_id = job.project_memory_space_id
            AND project_active.status = 'processing'
            AND (
                project_active.lock_expires_at IS NULL
                OR project_active.lock_expires_at > %(now)s
            )
      )
),
claim AS (
    SELECT job.id
    FROM graph_write_jobs AS job
    INNER JOIN candidates ON candidates.id = job.id
    WHERE candidates.project_rank = 1
      AND candidates.group_rank = 1
    ORDER BY
        CASE WHEN candidates.status = 'pending' THEN 0 ELSE 1 END,
        candidates.next_run_at,
        candidates.priority DESC,
        candidates.created_at
    LIMIT %(limit)s
    FOR UPDATE SKIP LOCKED
)
UPDATE graph_write_jobs AS job
SET status = 'processing',
    locked_at = %(now)s,
    locked_by = %(worker_id)s,
    lock_expires_at = %(lock_expires_at)s,
    updated_at = %(now)s
FROM claim
WHERE job.id = claim.id
RETURNING job.*
"""

_MARK_GRAPH_WRITE_SUCCEEDED_SQL = """
UPDATE graph_write_jobs
SET status = 'succeeded',
    locked_at = NULL,
    locked_by = NULL,
    lock_expires_at = NULL,
    last_error = NULL,
    updated_at = %(now)s
WHERE id = %(job_id)s
  AND status = 'processing'
  AND locked_by = %(locked_by)s
RETURNING *
"""

_MARK_GRAPH_WRITE_FAILED_SQL = """
UPDATE graph_write_jobs
SET attempts = attempts + 1,
    status = CASE
        WHEN attempts + 1 >= max_attempts THEN 'dead_letter'
        ELSE 'pending'
    END,
    next_run_at = CASE
        WHEN attempts + 1 >= max_attempts THEN next_run_at
        ELSE %(retry_at)s
    END,
    locked_at = NULL,
    locked_by = NULL,
    lock_expires_at = NULL,
    last_error = %(last_error)s,
    dead_letter_reason = CASE
        WHEN attempts + 1 >= max_attempts THEN %(last_error)s
        ELSE dead_letter_reason
    END,
    updated_at = %(now)s
WHERE id = %(job_id)s
  AND status = 'processing'
  AND locked_by = %(locked_by)s
RETURNING *
"""

_UPSERT_MEMORY_GRAPH_LINK_SQL = """
INSERT INTO memory_graph_links (
    id, backend, memory_id, source_event_id, project_memory_space_id,
    backend_space_id, backend_object_type, backend_object_id, link_type, created_at
) VALUES (
    %(id)s, %(backend)s, %(memory_id)s, %(source_event_id)s,
    %(project_memory_space_id)s, %(backend_space_id)s, %(backend_object_type)s,
    %(backend_object_id)s, %(link_type)s, %(created_at)s
)
ON CONFLICT (backend, backend_object_type, backend_object_id, memory_id, link_type)
DO NOTHING
RETURNING *
"""

_LIST_MEMORY_GRAPH_LINKS_BY_MEMORY_SQL = """
SELECT *
FROM memory_graph_links
WHERE memory_id = %(memory_id)s
ORDER BY created_at, id
"""
