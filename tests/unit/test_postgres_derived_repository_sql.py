"""SQL-boundary tests for derived memory repositories."""

import asyncio

from memwing.core.scope import EffectiveScope
from memwing.infrastructure.db.postgres import PostgresDataStore

from tests.unit.postgres_store_fixtures import (
    FakePostgresConnection,
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
    page_memory,
    page_memory_row,
    source_event,
    source_event_row,
    working_memory_entry,
    working_memory_entry_row,
)


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
    assert "topics_json" in queries
    assert "INSERT INTO memory_page_versions" in queries
    assert "INSERT INTO graph_write_jobs" in queries
    assert "memory_id" in queries
    assert "ON CONFLICT (idempotency_key)" in queries
    assert "INSERT INTO memory_graph_links" in queries
    graph_job_call = next(
        call for call in connection.calls if "INSERT INTO graph_write_jobs" in call[1]
    )
    assert graph_job_call[2]["memory_id"] == "memory_001"


def test_postgres_derived_repositories_execute_lane_d_e_f_read_contract_paths() -> None:
    source = source_event()
    memory = memory_item()
    version = memory_version()
    page = page_memory()
    scope = _effective_scope()
    connection = FakePostgresConnection(
        fetchrow_results=(
            memory_version_row(version),
            {"next_sequence": 13},
            {"token_count": 4},
        ),
        fetch_results=(
            (source_event_row(source),),
            (memory_item_row(memory),),
            (page_memory_row(page),),
        ),
    )

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            assert await tx.source_events.list_for_scope(scope=scope, limit=10) == (source,)
            assert await tx.memory_items.list_for_scope(scope=scope, limit=10) == (memory,)
            assert await tx.memory_versions.get_latest("memory_001") == version
            assert await tx.memory_pages.list_needs_rebuild(
                project_memory_space_id="project_001",
                limit=10,
            ) == (page,)
            assert await tx.working_memory_entries.next_sequence(
                project_memory_space_id="project_001",
                thread_id="thread_001",
            ) == 13
            assert await tx.working_memory_entries.sum_unflushed_tokens(
                project_memory_space_id="project_001",
                group_id="group_001",
                thread_id="thread_001",
            ) == 4

    asyncio.run(scenario())

    queries = "\n".join(call[1] for call in connection.calls)
    assert "FROM source_events" in queries
    assert "ORDER BY event_time ASC, id ASC" in queries
    assert "FROM memory_items" in queries
    assert "ORDER BY updated_at DESC, id" in queries
    assert "FROM memory_versions" in queries
    assert "ORDER BY version DESC" in queries
    assert "needs_rebuild = true" in queries
    assert "COALESCE(MAX(sequence), 0) + 1 AS next_sequence" in queries
    assert "COALESCE(SUM(token_count), 0) AS token_count" in queries
    assert connection.calls[0][2]["group_ids"] == ("group_001",)
    assert connection.calls[0][2]["thread_id"] == "thread_001"
    assert connection.calls[1][2]["group_ids"] == ("group_001",)
    assert connection.calls[3][2]["project_memory_space_id"] == "project_001"


def _effective_scope() -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("group_001",),
        thread_id="thread_001",
        shared_group_id=None,
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )
