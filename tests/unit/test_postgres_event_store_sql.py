"""SQL-boundary tests using a fake connection; these do not execute Postgres."""

import asyncio

from memwing.infrastructure.db.postgres import PostgresDataStore
from memwing.infrastructure.db.postgres_sql import session_pattern_to_postgres_like

from tests.unit.postgres_store_fixtures import (
    FakePostgresConnection,
    audit_event,
    audit_event_row,
    evidence_chunk,
    evidence_chunk_row,
    graph_write_job,
    graph_write_job_row,
    memory_graph_link,
    memory_graph_link_row,
    memory_item,
    memory_item_row,
    memory_page_version,
    memory_page_version_row,
    memory_version,
    memory_version_row,
    outbox_job,
    outbox_job_row,
    page_memory,
    page_memory_row,
    source_event,
    source_event_row,
    working_memory_entry,
    working_memory_entry_row,
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


def test_postgres_derived_repositories_execute_lane_d_e_f_insert_paths() -> None:
    chunk = evidence_chunk()
    working = working_memory_entry()
    memory = memory_item()
    version = memory_version()
    page = page_memory()
    page_version = memory_page_version()
    graph_job = graph_write_job()
    graph_link = memory_graph_link()
    connection = FakePostgresConnection(
        fetchrow_results=(
            evidence_chunk_row(chunk),
            working_memory_entry_row(working),
            memory_item_row(memory),
            memory_version_row(version),
            page_memory_row(page),
            memory_page_version_row(page_version),
            graph_write_job_row(graph_job),
            memory_graph_link_row(graph_link),
        )
    )

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            assert await tx.evidence_chunks.upsert_chunk(chunk) == chunk
            assert await tx.working_memory_entries.append(working) == working
            assert await tx.memory_items.upsert(memory) == memory
            assert await tx.memory_versions.record(version) == version
            assert await tx.memory_pages.upsert(page) == page
            assert await tx.memory_page_versions.record(page_version) == page_version
            assert await tx.graph_write_jobs.enqueue(graph_job) == graph_job
            assert await tx.memory_graph_links.upsert(graph_link) == graph_link

    asyncio.run(scenario())

    queries = "\n".join(call[1] for call in connection.calls)
    assert "INSERT INTO evidence_chunks" in queries
    assert "ON CONFLICT (source_event_id, chunk_index)" in queries
    assert "INSERT INTO working_memory_entries" in queries
    assert "INSERT INTO memory_items" in queries
    assert "INSERT INTO memory_versions" in queries
    assert "INSERT INTO memory_pages" in queries
    assert "INSERT INTO memory_page_versions" in queries
    assert "INSERT INTO graph_write_jobs" in queries
    assert "ON CONFLICT (idempotency_key)" in queries
    assert "INSERT INTO memory_graph_links" in queries
