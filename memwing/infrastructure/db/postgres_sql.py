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
    decision, reason_code, reason_text, source_event_ids, latency_ms, created_at
) VALUES (
    %(id)s, %(trace_id)s, %(entity_type)s, %(entity_id)s, %(stage)s, %(input_ref)s,
    %(output_ref)s, %(decision)s, %(reason_code)s, %(reason_text)s,
    %(source_event_ids)s, %(latency_ms)s, %(created_at)s
)
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
