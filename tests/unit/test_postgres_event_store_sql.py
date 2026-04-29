"""SQL-boundary tests using a fake connection; these do not execute Postgres."""

import asyncio

from memwing.infrastructure.db.postgres import PostgresDataStore
from memwing.infrastructure.db.postgres_sql import session_pattern_to_postgres_like

from tests.unit.postgres_store_fixtures import (
    FakePostgresConnection,
    audit_event,
    audit_event_row,
    outbox_job,
    outbox_job_row,
    source_event,
    source_event_row,
)


def test_postgres_remember_event_repositories_execute_transactional_insert_paths() -> None:
    source = source_event()
    audit = audit_event(source)
    job = outbox_job(source)
    connection = FakePostgresConnection(
        fetchrow_results=(
            source_event_row(source),
            audit_event_row(audit),
            outbox_job_row(job),
        )
    )

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            inserted, was_inserted = await tx.source_events.insert_if_absent(source)
            recorded = await tx.audit_events.record(audit)
            enqueued = await tx.outbox_jobs.enqueue(job)

        assert inserted == source
        assert was_inserted is True
        assert recorded == audit
        assert enqueued == job

    asyncio.run(scenario())

    assert connection.transaction_enters == 1
    assert connection.transaction_exits == 1
    queries = "\n".join(call[1] for call in connection.calls)
    assert "INSERT INTO source_events" in queries
    assert "ON CONFLICT DO NOTHING" in queries
    assert "INSERT INTO audit_events" in queries
    assert "INSERT INTO outbox_jobs" in queries
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in queries
    audit_call = next(call for call in connection.calls if "INSERT INTO audit_events" in call[1])
    assert audit_call[2]["actor_id"] == "system"
    assert audit_call[2]["idempotency_key"] == "audit:source_001"


def test_postgres_audit_record_loads_existing_idempotent_event() -> None:
    source = source_event()
    audit = audit_event(source)
    connection = FakePostgresConnection(
        fetchrow_results=(
            None,
            audit_event_row(audit),
        )
    )

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            recorded = await tx.audit_events.record(audit)

        assert recorded == audit

    asyncio.run(scenario())

    queries = "\n".join(call[1] for call in connection.calls)
    assert "ON CONFLICT (entity_type, entity_id, idempotency_key)" in queries
    assert "WHERE idempotency_key IS NOT NULL" in queries
    assert "FROM audit_events" in connection.calls[1][1]
    assert connection.calls[1][2]["idempotency_key"] == "audit:source_001"


def test_postgres_source_insert_if_absent_loads_existing_conflict_row() -> None:
    source = source_event()
    connection = FakePostgresConnection(fetchrow_results=(None, source_event_row(source)))

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            existing, inserted = await tx.source_events.insert_if_absent(source)

        assert existing == source
        assert inserted is False

    asyncio.run(scenario())

    assert "SELECT *\nFROM source_events" in connection.calls[1][1]
    assert connection.calls[1][2]["runtime_event_idempotency_key"] == "runtime-key-001"


def test_postgres_session_key_pattern_like_escapes_sql_wildcards() -> None:
    assert session_pattern_to_postgres_like("feature/*") == "feature/%"
    assert session_pattern_to_postgres_like("session_100%_*") == "session!_100!%!_%"
    assert session_pattern_to_postgres_like(r"path\\*") == r"path\\%"
    assert session_pattern_to_postgres_like("bang!_*") == "bang!!!_%"


def test_postgres_scope_binding_queries_preserve_authoritative_server_lookup() -> None:
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
                "shared_group_id": "shared_001",
            },
        ),
        fetch_results=(
            (
                {
                    "runtime": "openclaw",
                    "agent_id": "agent_001",
                    "workspace_id": None,
                    "session_key_pattern": "session_*",
                    "project_memory_space_id": "project_001",
                },
            ),
            (
                {
                    "platform": "feishu",
                    "tenant_id": "tenant_001",
                    "channel_id": "chat_001",
                    "thread_id": None,
                    "project_memory_space_id": "project_001",
                    "group_id": "group_001",
                },
            ),
        ),
    )
    store = PostgresDataStore(connection)

    async def scenario() -> None:
        assert await store.get_project_memory_space("project_001") is not None
        assert (
            await store.list_runtime_scope_binding_candidates(
                runtime="openclaw",
                agent_id="agent_001",
                workspace_id=None,
                session_id="session_001",
            )
        ) != ()
        assert (
            await store.list_platform_scope_binding_candidates(
                platform="feishu",
                tenant_id="tenant_001",
                channel_id="chat_001",
                thread_id="thread_001",
            )
        ) != ()
        assert (
            await store.get_group_memory_settings(
                project_memory_space_id="project_001",
                group_id="group_001",
            )
        ) is not None

    asyncio.run(scenario())

    queries = "\n".join(call[1] for call in connection.calls)
    normalized_queries = " ".join(queries.split())
    assert "workspace_id IS NOT DISTINCT FROM %(workspace_id)s" in queries
    assert "replace(session_key_pattern, '!', '!!')" in normalized_queries
    assert "'%', '!%'" in normalized_queries
    assert "'_', '!_'" in normalized_queries
    assert "'*', '%'" in normalized_queries
    assert "ESCAPE '!'" in normalized_queries
    assert "ORDER BY length(session_key_pattern) DESC" not in queries
    assert "LIMIT 1" not in queries
    assert "thread_id IS NOT DISTINCT FROM %(thread_id)s OR thread_id IS NULL" in queries
    assert "ORDER BY (thread_id IS NOT NULL) DESC" not in queries
