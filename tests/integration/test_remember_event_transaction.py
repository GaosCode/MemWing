import asyncio
from datetime import UTC, datetime

import pytest

from memwing.api.platform import PlatformEvent, PlatformRef
from memwing.application.gateway_service import MemoryGateway
from memwing.application.remember_event_command import (
    RememberEventCommand,
    platform_event_to_remember_command,
)
from memwing.application.scope_resolver import ScopeResolutionError, ScopeResolver
from memwing.core.scope import PlatformScopeBinding, ProjectMemorySpace
from memwing.infrastructure.db.in_memory import InMemoryDataStore


def _platform_event(content: str, raw_payload: dict[str, object]) -> PlatformEvent:
    return PlatformEvent(
        platform_ref=PlatformRef(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id="thread_001",
            message_id="message_001",
        ),
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id="user_001",
        author_name="Ada",
        source_type="text",
        content=content,
        source_url=None,
        event_time=datetime(2026, 4, 28, tzinfo=UTC),
        raw_payload=raw_payload,
    )


def _store(*, fail_on_outbox_job_type: str | None = None) -> InMemoryDataStore:
    store = InMemoryDataStore(fail_on_outbox_job_type=fail_on_outbox_job_type)
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Demo",
            default_safe_mode_enabled=False,
        )
    )
    store.add_platform_scope_binding(
        PlatformScopeBinding(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id="thread_001",
            project_memory_space_id="project_001",
            group_id="group_001",
        )
    )
    return store


def test_remember_event_commits_source_audit_and_generic_outbox_atomically() -> None:
    store = _store()
    gateway = MemoryGateway(store, ScopeResolver(store))
    command = platform_event_to_remember_command(
        _platform_event(
            "This week prioritizes Feishu docs memory.",
            {"message_id": "message_001", "text": "This week prioritizes Feishu docs memory."},
        )
    )

    result = asyncio.run(gateway.remember_event(command))

    assert result.accepted is True
    assert isinstance(command, RememberEventCommand)
    assert len(store.source_events) == 1
    assert len(store.audit_events) == 1
    assert len(store.outbox_jobs) == 4
    assert store.audit_events[0].stage == "remember_event.captured"
    assert {job.job_type for job in store.outbox_jobs} == {
        "evidence.index_source_event",
        "working_memory.append",
        "page_memory.maybe_rebuild",
        "long_term_filter.classify",
    }
    assert {
        job.job_type: job.aggregate_key
        for job in store.outbox_jobs
        if job.job_type in ("page_memory.maybe_rebuild", "long_term_filter.classify")
    } == {
        "page_memory.maybe_rebuild": "page_memory:project_001:thread:thread_001",
        "long_term_filter.classify": "long_term_filter:project_001:group_001:thread_001:",
    }
    assert all("graph" not in job.job_type for job in store.outbox_jobs)
    assert store.source_events[0].metadata["source_ref"] == {
        "kind": "platform",
        "platform": "feishu",
        "tenant_id": "tenant_001",
        "channel_id": "chat_001",
        "thread_id": "thread_001",
        "message_id": "message_001",
    }


def test_memory_gateway_rejects_adapter_events_before_normalization() -> None:
    store = _store()
    gateway = MemoryGateway(store, ScopeResolver(store))

    with pytest.raises(TypeError, match="RememberEventCommand"):
        asyncio.run(
            gateway.remember_event(
                _platform_event(
                    "Adapter events must be normalized before gateway.",
                    {"message_id": "message_adapter"},
                )
            )
        )


def test_raw_payload_hash_dedupes_source_and_outbox() -> None:
    store = _store()
    gateway = MemoryGateway(store, ScopeResolver(store))
    payload = {"message_id": "message_001", "text": "Same raw event."}

    first = asyncio.run(
        gateway.remember_event(
            platform_event_to_remember_command(_platform_event("Same raw event.", payload))
        )
    )
    second = asyncio.run(
        gateway.remember_event(
            platform_event_to_remember_command(_platform_event("Changed content", payload))
        )
    )

    assert second.duplicate_of == first.source_event_id
    assert len(store.source_events) == 1
    assert len(store.outbox_jobs) == 4
    assert len(store.audit_events) == 1


def test_transaction_rollback_leaves_no_partial_source_outbox_or_audit() -> None:
    store = _store(fail_on_outbox_job_type="working_memory.append")
    gateway = MemoryGateway(store, ScopeResolver(store))

    with pytest.raises(RuntimeError, match="working_memory.append"):
        asyncio.run(
            gateway.remember_event(
                platform_event_to_remember_command(
                    _platform_event(
                        "Rollback must remove partial writes.",
                        {"message_id": "message_rollback"},
                    )
                )
            )
        )

    assert store.source_events == ()
    assert store.outbox_jobs == ()
    assert store.audit_events == ()


def test_scope_failure_records_rejected_audit_without_source_or_outbox() -> None:
    store = InMemoryDataStore()
    gateway = MemoryGateway(store, ScopeResolver(store))

    with pytest.raises(ScopeResolutionError):
        asyncio.run(
            gateway.remember_event(
                platform_event_to_remember_command(
                    _platform_event(
                        "Missing binding should be audited.",
                        {"message_id": "message_missing_binding"},
                    )
                )
            )
        )

    assert store.source_events == ()
    assert store.outbox_jobs == ()
    assert len(store.audit_events) == 1
    assert store.audit_events[0].stage == "remember_event.rejected"
    assert store.audit_events[0].reason_code == "scope_resolution_failed"
