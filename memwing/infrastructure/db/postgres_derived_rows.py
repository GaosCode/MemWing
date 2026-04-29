from __future__ import annotations

from memwing.core.models import (
    EvidenceChunk,
    GraphWriteJob,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryItem,
    MemoryPageVersion,
    MemoryRoute,
    MemoryStatus,
    MemoryVersion,
    PageMemory,
    WorkingMemoryEntry,
)

from .postgres_rows import Row
from .postgres_rows import (
    _bool,
    _datetime,
    _float,
    _int,
    _optional_datetime,
    _optional_float,
    _optional_text,
    _sequence,
    _text,
    _float_sequence_or_none,
)


def evidence_chunk_from_row(row: Row) -> EvidenceChunk:
    return EvidenceChunk(
        id=_text(row, "id"),
        source_event_id=_text(row, "source_event_id"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        group_id=_optional_text(row, "group_id"),
        thread_id=_optional_text(row, "thread_id"),
        shared_group_id=_optional_text(row, "shared_group_id"),
        chunk_text=_text(row, "chunk_text"),
        chunk_index=_int(row, "chunk_index"),
        embedding_model=_optional_text(row, "embedding_model"),
        embedding_ref=_optional_text(row, "embedding_ref"),
        embedding_vector=_float_sequence_or_none(row, "embedding_vector"),
        invalidated_at=_optional_datetime(row, "invalidated_at"),
        created_at=_datetime(row, "created_at"),
    )


def working_memory_entry_from_row(row: Row) -> WorkingMemoryEntry:
    return WorkingMemoryEntry(
        id=_text(row, "id"),
        source_event_id=_text(row, "source_event_id"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        group_id=_optional_text(row, "group_id"),
        thread_id=_optional_text(row, "thread_id"),
        shared_group_id=_optional_text(row, "shared_group_id"),
        content=_text(row, "content"),
        token_count=_int(row, "token_count"),
        sequence=_int(row, "sequence"),
        flushed_at=_optional_datetime(row, "flushed_at"),
        created_at=_datetime(row, "created_at"),
    )


def memory_item_from_row(row: Row) -> MemoryItem:
    return MemoryItem(
        id=_text(row, "id"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        group_id=_optional_text(row, "group_id"),
        thread_id=_optional_text(row, "thread_id"),
        shared_group_id=_optional_text(row, "shared_group_id"),
        route=MemoryRoute(_text(row, "route")),
        display_type=MemoryDisplayType(_text(row, "display_type")),
        title=_text(row, "title"),
        content=_text(row, "content"),
        summary=_optional_text(row, "summary"),
        source_event_ids=_sequence(row, "source_event_ids"),
        primary_source_event_id=_optional_text(row, "primary_source_event_id"),
        status=MemoryStatus(_text(row, "status")),
        event_time=_optional_datetime(row, "event_time"),
        valid_from=_optional_datetime(row, "valid_from"),
        valid_to=_optional_datetime(row, "valid_to"),
        original_score=_float(row, "original_score"),
        half_life_days=_int(row, "half_life_days"),
        last_reviewed_at=_optional_datetime(row, "last_reviewed_at"),
        last_confirmed_at=_optional_datetime(row, "last_confirmed_at"),
        last_recalled_at=_optional_datetime(row, "last_recalled_at"),
        recall_count=_int(row, "recall_count"),
        cached_decayed_score=_optional_float(row, "cached_decayed_score"),
        last_decay_computed_at=_optional_datetime(row, "last_decay_computed_at"),
        pinned=_bool(row, "pinned"),
        created_by=_text(row, "created_by"),
        created_at=_datetime(row, "created_at"),
        activated_at=_optional_datetime(row, "activated_at"),
        updated_at=_datetime(row, "updated_at"),
        archived_at=_optional_datetime(row, "archived_at"),
        hidden_at=_optional_datetime(row, "hidden_at"),
        invalidated_at=_optional_datetime(row, "invalidated_at"),
        removed_at=_optional_datetime(row, "removed_at"),
    )


def memory_version_from_row(row: Row) -> MemoryVersion:
    return MemoryVersion(
        id=_text(row, "id"),
        memory_id=_text(row, "memory_id"),
        version=_int(row, "version"),
        title=_text(row, "title"),
        content=_text(row, "content"),
        summary=_optional_text(row, "summary"),
        status=MemoryStatus(_text(row, "status")),
        source_event_ids=_sequence(row, "source_event_ids"),
        changed_by=_text(row, "changed_by"),
        change_reason=_text(row, "change_reason"),
        created_at=_datetime(row, "created_at"),
    )


def page_memory_from_row(row: Row) -> PageMemory:
    return PageMemory(
        id=_text(row, "id"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        group_id=_optional_text(row, "group_id"),
        thread_id=_optional_text(row, "thread_id"),
        shared_group_id=_optional_text(row, "shared_group_id"),
        scope_type=_text(row, "scope_type"),
        scope_id=_text(row, "scope_id"),
        title=_text(row, "title"),
        brief=_text(row, "brief"),
        source_event_ids=_sequence(row, "source_event_ids"),
        linked_memory_item_ids=_sequence(row, "linked_memory_item_ids"),
        version=_int(row, "version"),
        needs_rebuild=_bool(row, "needs_rebuild"),
        created_at=_datetime(row, "created_at"),
        updated_at=_datetime(row, "updated_at"),
    )


def memory_page_version_from_row(row: Row) -> MemoryPageVersion:
    return MemoryPageVersion(
        id=_text(row, "id"),
        page_id=_text(row, "page_id"),
        version=_int(row, "version"),
        title=_text(row, "title"),
        brief=_text(row, "brief"),
        source_event_ids=_sequence(row, "source_event_ids"),
        linked_memory_item_ids=_sequence(row, "linked_memory_item_ids"),
        changed_by=_text(row, "changed_by"),
        change_reason=_text(row, "change_reason"),
        created_at=_datetime(row, "created_at"),
    )


def graph_write_job_from_row(row: Row) -> GraphWriteJob:
    return GraphWriteJob(
        id=_text(row, "id"),
        backend=_text(row, "backend"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        thread_id=_optional_text(row, "thread_id"),
        saga_id=_optional_text(row, "saga_id"),
        source_event_ids=_sequence(row, "source_event_ids"),
        route=MemoryRoute(_text(row, "route")),
        status=_text(row, "status"),
        idempotency_key=_text(row, "idempotency_key"),
        attempts=_int(row, "attempts"),
        max_attempts=_int(row, "max_attempts"),
        priority=_int(row, "priority"),
        next_run_at=_datetime(row, "next_run_at"),
        dead_letter_reason=_optional_text(row, "dead_letter_reason"),
        last_error=_optional_text(row, "last_error"),
        locked_at=_optional_datetime(row, "locked_at"),
        locked_by=_optional_text(row, "locked_by"),
        lock_expires_at=_optional_datetime(row, "lock_expires_at"),
        created_at=_datetime(row, "created_at"),
        updated_at=_datetime(row, "updated_at"),
    )


def memory_graph_link_from_row(row: Row) -> MemoryGraphLink:
    return MemoryGraphLink(
        id=_text(row, "id"),
        backend=_text(row, "backend"),
        memory_id=_text(row, "memory_id"),
        source_event_id=_text(row, "source_event_id"),
        project_memory_space_id=_text(row, "project_memory_space_id"),
        backend_space_id=_text(row, "backend_space_id"),
        backend_object_type=_text(row, "backend_object_type"),
        backend_object_id=_text(row, "backend_object_id"),
        link_type=_text(row, "link_type"),
        created_at=_datetime(row, "created_at"),
    )
