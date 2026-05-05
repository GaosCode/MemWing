from __future__ import annotations

import asyncio

from memwing.core.models import PushCandidate
from memwing.infrastructure.db.postgres import PostgresDataStore

from tests.unit.postgres_store_fixtures import (
    FakePostgresConnection,
    audit_event,
    audit_event_row,
    graph_write_job,
    graph_write_job_row,
    outbox_job,
    outbox_job_row,
    source_event,
)


def test_postgres_control_projection_lists_scope_directory_without_literal_percent_patterns() -> None:
    now = source_event().created_at
    connection = FakePostgresConnection(
        fetch_results=(
            (
                {
                    "id": "benchmark:20260505-115148:bs001",
                    "name": "Benchmark bs001",
                    "default_safe_mode_enabled": False,
                    "memory_count": 1,
                    "source_event_count": 1,
                    "page_count": 0,
                    "directory_updated_at": now,
                },
            ),
            (
                {
                    "group_id": "benchmark:bs001",
                    "thread_id": "benchmark:bs001",
                    "safe_mode_enabled": False,
                    "shared_group_id": None,
                    "memory_count": 1,
                    "source_event_count": 1,
                    "updated_at": now,
                },
            ),
        )
    )

    async def scenario() -> None:
        records = await PostgresDataStore(connection).list_project_memory_space_directory(
            include_benchmark=True,
            query="bs001",
            limit=10,
            cursor=None,
        )

        assert records[0].project.id == "benchmark:20260505-115148:bs001"
        assert records[0].groups[0].group_id == "benchmark:bs001"
        assert records[0].groups[0].threads[0].thread_id == "benchmark:bs001"

    asyncio.run(scenario())

    directory_call = connection.calls[0]
    assert directory_call[0] == "fetch"
    assert "'%%'" not in directory_call[1]
    assert "p.id NOT LIKE %(benchmark_pattern)s" in directory_call[1]
    assert "%(query_pattern)s::text IS NULL" in directory_call[1]
    assert directory_call[2]["benchmark_pattern"] == "benchmark:%"
    assert directory_call[2]["query_pattern"] == "%bs001%"


def test_postgres_control_projection_lists_jobs_for_project() -> None:
    source = source_event()
    graph_job = graph_write_job()
    outbox = outbox_job(source)
    connection = FakePostgresConnection(
        fetch_results=((graph_write_job_row(graph_job),), (outbox_job_row(outbox),))
    )

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            graph_jobs = await tx.graph_write_jobs.list_for_project(
                project_memory_space_id="project_001",
                limit=10,
            )
            outbox_jobs = await tx.outbox_jobs.list_for_project(
                project_memory_space_id="project_001",
                limit=10,
            )

        assert graph_jobs == (graph_job,)
        assert outbox_jobs == (outbox,)

    asyncio.run(scenario())

    graph_call = connection.calls[0]
    outbox_call = connection.calls[1]
    assert graph_call[0] == "fetch"
    assert "FROM graph_write_jobs" in graph_call[1]
    assert "project_memory_space_id = %(project_memory_space_id)s" in graph_call[1]
    assert graph_call[2]["project_memory_space_id"] == "project_001"
    assert outbox_call[0] == "fetch"
    assert "FROM outbox_jobs" in outbox_call[1]
    assert "project_memory_space_id = %(project_memory_space_id)s" in outbox_call[1]
    assert outbox_call[2]["limit"] == 10


def test_postgres_control_projection_lists_push_candidates_and_audit_refs() -> None:
    source = source_event()
    push = _push_candidate()
    audit = audit_event(source)
    connection = FakePostgresConnection(
        fetch_results=((_push_candidate_row(push),), (audit_event_row(audit),))
    )

    async def scenario() -> None:
        async with PostgresDataStore(connection).transaction() as tx:
            push_candidates = await tx.push_candidates.list_for_project(
                project_memory_space_id="project_001",
                limit=10,
            )
            audit_events = await tx.audit_events.list_for_entity(
                entity_type="source_event",
                entity_id=source.id,
                limit=20,
            )

        assert push_candidates == (push,)
        assert audit_events == (audit,)

    asyncio.run(scenario())

    push_call = connection.calls[0]
    audit_call = connection.calls[1]
    assert push_call[0] == "fetch"
    assert "FROM push_candidates" in push_call[1]
    assert "ORDER BY updated_at DESC" in push_call[1]
    assert audit_call[0] == "fetch"
    assert "FROM audit_events" in audit_call[1]
    assert "entity_type = %(entity_type)s" in audit_call[1]
    assert audit_call[2]["entity_id"] == source.id


def _push_candidate() -> PushCandidate:
    now = source_event().created_at
    return PushCandidate(
        id="push_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        type="forgetting_review",
        title="Review Demo scope",
        content="Demo scope needs review.",
        memory_item_ids=("memory_001",),
        source_event_ids=("source_001",),
        trigger_reason="score_below_threshold",
        trigger_source="forgetting_review",
        priority=100,
        expires_at=None,
        status="pending",
        cooldown_key="forgetting_review:memory_001",
        created_at=now,
        updated_at=now,
    )


def _push_candidate_row(candidate: PushCandidate) -> dict[str, object]:
    return {
        "id": candidate.id,
        "project_memory_space_id": candidate.project_memory_space_id,
        "group_id": candidate.group_id,
        "thread_id": candidate.thread_id,
        "shared_group_id": candidate.shared_group_id,
        "type": candidate.type,
        "title": candidate.title,
        "content": candidate.content,
        "memory_item_ids": candidate.memory_item_ids,
        "source_event_ids": candidate.source_event_ids,
        "trigger_reason": candidate.trigger_reason,
        "trigger_source": candidate.trigger_source,
        "priority": candidate.priority,
        "expires_at": candidate.expires_at,
        "status": candidate.status,
        "cooldown_key": candidate.cooldown_key,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
    }
