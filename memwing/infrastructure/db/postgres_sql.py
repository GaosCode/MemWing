POSTGRES_LIKE_ESCAPE = "!"

SESSION_KEY_PATTERN_LIKE_SQL = f"""
replace(
    replace(
        replace(
            replace(session_key_pattern, '{POSTGRES_LIKE_ESCAPE}', '{POSTGRES_LIKE_ESCAPE}{POSTGRES_LIKE_ESCAPE}'),
            '%',
            '{POSTGRES_LIKE_ESCAPE}%'
        ),
        '_',
        '{POSTGRES_LIKE_ESCAPE}_'
    ),
    '*',
    '%'
) ESCAPE '{POSTGRES_LIKE_ESCAPE}'
"""


def session_pattern_to_postgres_like(pattern: str) -> str:
    parts: list[str] = []
    for char in pattern:
        if char == "*":
            parts.append("%")
        elif char in (POSTGRES_LIKE_ESCAPE, "%", "_"):
            parts.append(f"{POSTGRES_LIKE_ESCAPE}{char}")
        else:
            parts.append(char)
    return "".join(parts)


_INSERT_SOURCE_EVENT_SQL = """
INSERT INTO source_events (
    id, project_memory_space_id, group_id, thread_id, shared_group_id,
    author_id, author_name, source_type, content, content_preview, source_url,
    event_time, raw_payload_hash, runtime_event_idempotency_key, metadata_json,
    purged_at, purged_by, purge_reason, purge_level, graph_backend_raw_retained,
    created_at
) VALUES (
    %(id)s, %(project_memory_space_id)s, %(group_id)s, %(thread_id)s, %(shared_group_id)s,
    %(author_id)s, %(author_name)s, %(source_type)s, %(content)s, %(content_preview)s,
    %(source_url)s, %(event_time)s, %(raw_payload_hash)s, %(runtime_event_idempotency_key)s,
    %(metadata_json)s, %(purged_at)s, %(purged_by)s, %(purge_reason)s, %(purge_level)s,
    %(graph_backend_raw_retained)s, %(created_at)s
)
ON CONFLICT DO NOTHING
RETURNING *
"""

_SELECT_EXISTING_SOURCE_EVENT_SQL = """
SELECT *
FROM source_events
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND (
    raw_payload_hash = %(raw_payload_hash)s
    OR (
        %(runtime_event_idempotency_key)s IS NOT NULL
        AND runtime_event_idempotency_key = %(runtime_event_idempotency_key)s
    )
  )
ORDER BY created_at
LIMIT 1
"""

_INSERT_AUDIT_EVENT_SQL = """
INSERT INTO audit_events (
    id, trace_id, entity_type, entity_id, stage, input_ref, output_ref,
    decision, reason_code, reason_text, source_event_ids, latency_ms, created_at,
    actor_id, idempotency_key, action_ref, lifecycle_revision
) VALUES (
    %(id)s, %(trace_id)s, %(entity_type)s, %(entity_id)s, %(stage)s, %(input_ref)s,
    %(output_ref)s, %(decision)s, %(reason_code)s, %(reason_text)s,
    %(source_event_ids)s, %(latency_ms)s, %(created_at)s, %(actor_id)s,
    %(idempotency_key)s, %(action_ref)s, %(lifecycle_revision)s
)
ON CONFLICT (entity_type, entity_id, idempotency_key)
WHERE idempotency_key IS NOT NULL
DO NOTHING
RETURNING *
"""

_SELECT_AUDIT_EVENT_BY_IDEMPOTENCY_SQL = """
SELECT *
FROM audit_events
WHERE entity_type = %(entity_type)s
  AND entity_id = %(entity_id)s
  AND idempotency_key = %(idempotency_key)s
LIMIT 1
"""

_LIST_AUDIT_EVENTS_FOR_ENTITY_SQL = """
SELECT *
FROM audit_events
WHERE entity_type = %(entity_type)s
  AND entity_id = %(entity_id)s
ORDER BY created_at DESC, id DESC
LIMIT %(limit)s
"""

_LIST_SOURCE_EVENTS_FOR_SCOPE_SQL = """
SELECT *
FROM source_events
WHERE project_memory_space_id = %(project_memory_space_id)s
  AND purged_at IS NULL
  AND purge_level = 'none'
  AND (%(group_ids)s::text[] IS NULL OR group_id = ANY(%(group_ids)s::text[]))
  AND (%(thread_id)s::text IS NULL OR thread_id IS NOT DISTINCT FROM %(thread_id)s::text)
  AND (
      %(shared_group_id)s::text IS NULL
      OR shared_group_id IS NOT DISTINCT FROM %(shared_group_id)s::text
  )
ORDER BY event_time ASC, id ASC
LIMIT %(limit)s
"""

_LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL = """
WITH recent_source_events AS (
    SELECT *
    FROM source_events
    WHERE project_memory_space_id = %(project_memory_space_id)s
      AND purged_at IS NULL
      AND purge_level = 'none'
      AND (%(group_ids)s::text[] IS NULL OR group_id = ANY(%(group_ids)s::text[]))
      AND (%(thread_id)s::text IS NULL OR thread_id IS NOT DISTINCT FROM %(thread_id)s::text)
      AND (
          %(shared_group_id)s::text IS NULL
          OR shared_group_id IS NOT DISTINCT FROM %(shared_group_id)s::text
      )
    ORDER BY event_time DESC, id DESC
    LIMIT %(limit)s
)
SELECT *
FROM recent_source_events
ORDER BY event_time ASC, id ASC
"""

_REDACT_SOURCE_EVENT_SQL = """
UPDATE source_events
SET content = %(redacted_content)s,
    content_preview = %(redacted_content)s,
    purged_at = %(purged_at)s,
    purged_by = %(purged_by)s,
    purge_reason = %(purge_reason)s,
    purge_level = %(purge_level)s,
    graph_backend_raw_retained = %(graph_backend_raw_retained)s
WHERE id = %(source_event_id)s
RETURNING *
"""

_INSERT_OUTBOX_JOB_SQL = """
INSERT INTO outbox_jobs (
    id, project_memory_space_id, source_event_id, job_type, payload_json,
    status, idempotency_key, aggregate_key, attempts, max_attempts, priority,
    next_run_at, locked_at, locked_by, lock_expires_at, last_error,
    dead_letter_reason, created_at, updated_at
) VALUES (
    %(id)s, %(project_memory_space_id)s, %(source_event_id)s, %(job_type)s,
    %(payload_json)s, %(status)s, %(idempotency_key)s, %(aggregate_key)s,
    %(attempts)s, %(max_attempts)s, %(priority)s, %(next_run_at)s,
    %(locked_at)s, %(locked_by)s, %(lock_expires_at)s, %(last_error)s,
    %(dead_letter_reason)s, %(created_at)s, %(updated_at)s
)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING *
"""

_LIST_OUTBOX_JOBS_FOR_PROJECT_SQL = """
SELECT *
FROM outbox_jobs
WHERE project_memory_space_id = %(project_memory_space_id)s
ORDER BY {order_by}
LIMIT %(limit)s
"""

_CLAIM_OUTBOX_JOBS_SQL = """
WITH claim AS (
    SELECT id
    FROM outbox_jobs
    WHERE (status = 'pending' AND next_run_at <= %(now)s)
       OR (status = 'processing' AND lock_expires_at <= %(now)s)
    ORDER BY
        CASE WHEN status = 'pending' THEN 0 ELSE 1 END,
        next_run_at,
        priority DESC,
        created_at
    LIMIT %(limit)s
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox_jobs AS job
SET status = 'processing',
    locked_at = %(now)s,
    locked_by = %(worker_id)s,
    lock_expires_at = %(lock_expires_at)s,
    updated_at = %(now)s
FROM claim
WHERE job.id = claim.id
RETURNING job.*
"""

_CLAIM_OUTBOX_JOBS_FOR_PROJECT_SQL = """
WITH claim AS (
    SELECT id
    FROM outbox_jobs
    WHERE project_memory_space_id = %(project_memory_space_id)s
      AND (
          (status = 'pending' AND next_run_at <= %(now)s)
       OR (status = 'processing' AND lock_expires_at <= %(now)s)
      )
    ORDER BY
        CASE WHEN status = 'pending' THEN 0 ELSE 1 END,
        next_run_at,
        priority DESC,
        created_at
    LIMIT %(limit)s
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox_jobs AS job
SET status = 'processing',
    locked_at = %(now)s,
    locked_by = %(worker_id)s,
    lock_expires_at = %(lock_expires_at)s,
    updated_at = %(now)s
FROM claim
WHERE job.id = claim.id
RETURNING job.*
"""

_MARK_OUTBOX_SUCCEEDED_SQL = """
UPDATE outbox_jobs
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

_MARK_OUTBOX_FAILED_SQL = """
UPDATE outbox_jobs
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

_RETRY_OUTBOX_DEAD_LETTER_SQL = """
UPDATE outbox_jobs
SET status = 'pending',
    locked_at = NULL,
    locked_by = NULL,
    lock_expires_at = NULL,
    last_error = NULL,
    dead_letter_reason = NULL,
    next_run_at = %(now)s,
    updated_at = %(now)s
WHERE id = %(job_id)s
  AND project_memory_space_id = %(project_memory_space_id)s
  AND status = 'dead_letter'
RETURNING *
"""
