from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol

from memwing.core.models import (
    EvidenceChunk,
    GraphWriteJob,
    MemoryGraphLink,
    MemoryItem,
    MemoryPageVersion,
    MemoryVersion,
    PageMemory,
    PageMemoryScopeType,
    WorkingMemoryEntry,
)
from memwing.ports.event_store import OutboxLockOwnershipError

from .in_memory_state import InMemoryState


class InMemoryTransactionView(Protocol):
    state: InMemoryState


class InMemoryEvidenceChunkRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert_chunk(self, chunk: EvidenceChunk) -> EvidenceChunk:
        key = (chunk.source_event_id, chunk.chunk_index)
        existing_id = self._tx.state.evidence_by_source_chunk.get(key)
        if existing_id is not None:
            existing = self._tx.state.evidence_chunks[existing_id]
            updated = replace(
                existing,
                chunk_text=chunk.chunk_text,
                embedding_model=chunk.embedding_model,
                embedding_ref=chunk.embedding_ref,
                embedding_vector=chunk.embedding_vector,
                invalidated_at=chunk.invalidated_at,
            )
            self._tx.state.evidence_chunks[existing_id] = updated
            return updated

        self._tx.state.evidence_chunks[chunk.id] = chunk
        self._tx.state.evidence_by_source_chunk[key] = chunk.id
        return chunk

    async def mark_source_redacted(
        self,
        *,
        source_event_id: str,
        invalidated_at: datetime,
    ) -> int:
        count = 0
        for chunk_id, chunk in tuple(self._tx.state.evidence_chunks.items()):
            if chunk.source_event_id == source_event_id and chunk.invalidated_at is None:
                self._tx.state.evidence_chunks[chunk_id] = replace(
                    chunk,
                    invalidated_at=invalidated_at,
                )
                count += 1
        return count


class InMemoryWorkingMemoryRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def append(self, entry: WorkingMemoryEntry) -> WorkingMemoryEntry:
        key = (entry.project_memory_space_id, entry.thread_id, entry.sequence)
        existing_id = self._tx.state.working_memory_by_scope_sequence.get(key)
        if existing_id is not None:
            return self._tx.state.working_memory_entries[existing_id]

        self._tx.state.working_memory_entries[entry.id] = entry
        self._tx.state.working_memory_by_scope_sequence[key] = entry.id
        return entry

    async def list_recent(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        limit: int,
    ) -> tuple[WorkingMemoryEntry, ...]:
        entries = [
            entry
            for entry in self._tx.state.working_memory_entries.values()
            if entry.project_memory_space_id == project_memory_space_id
            and entry.thread_id == thread_id
            and entry.flushed_at is None
        ]
        entries.sort(key=lambda entry: entry.sequence, reverse=True)
        return tuple(entries[:limit])

    async def mark_flushed(
        self,
        *,
        project_memory_space_id: str,
        thread_id: str | None,
        through_sequence: int,
        flushed_at: datetime,
    ) -> int:
        count = 0
        for entry_id, entry in tuple(self._tx.state.working_memory_entries.items()):
            if (
                entry.project_memory_space_id == project_memory_space_id
                and entry.thread_id == thread_id
                and entry.sequence <= through_sequence
                and entry.flushed_at is None
            ):
                self._tx.state.working_memory_entries[entry_id] = replace(
                    entry,
                    flushed_at=flushed_at,
                )
                count += 1
        return count


class InMemoryMemoryItemRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert(self, item: MemoryItem) -> MemoryItem:
        self._tx.state.memory_items[item.id] = item
        return item

    async def get(self, memory_id: str) -> MemoryItem | None:
        return self._tx.state.memory_items.get(memory_id)

    async def list_by_source_event(self, source_event_id: str) -> tuple[MemoryItem, ...]:
        return tuple(
            item
            for item in self._tx.state.memory_items.values()
            if source_event_id in item.source_event_ids
        )


class InMemoryMemoryVersionRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def record(self, version: MemoryVersion) -> MemoryVersion:
        key = (version.memory_id, version.version)
        existing_id = self._tx.state.memory_version_by_memory_version.get(key)
        if existing_id is not None:
            return self._tx.state.memory_versions[existing_id]

        self._tx.state.memory_versions[version.id] = version
        self._tx.state.memory_version_by_memory_version[key] = version.id
        return version


class InMemoryMemoryPageRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert(self, page: PageMemory) -> PageMemory:
        key = (page.project_memory_space_id, page.scope_type, page.scope_id)
        existing_id = self._tx.state.memory_page_by_scope.get(key)
        if existing_id is not None:
            existing = self._tx.state.memory_pages[existing_id]
            updated = replace(
                existing,
                group_id=page.group_id,
                thread_id=page.thread_id,
                shared_group_id=page.shared_group_id,
                title=page.title,
                brief=page.brief,
                source_event_ids=page.source_event_ids,
                linked_memory_item_ids=page.linked_memory_item_ids,
                version=page.version,
                needs_rebuild=page.needs_rebuild,
                created_at=page.created_at,
                updated_at=page.updated_at,
            )
            self._tx.state.memory_pages[existing_id] = updated
            return updated

        self._tx.state.memory_pages[page.id] = page
        self._tx.state.memory_page_by_scope[key] = page.id
        return page

    async def get_by_scope(
        self,
        *,
        project_memory_space_id: str,
        scope_type: PageMemoryScopeType,
        scope_id: str,
    ) -> PageMemory | None:
        page_id = self._tx.state.memory_page_by_scope.get(
            (project_memory_space_id, scope_type, scope_id)
        )
        if page_id is None:
            return None
        return self._tx.state.memory_pages[page_id]

    async def mark_needs_rebuild_for_source(
        self,
        *,
        source_event_id: str,
        updated_at: datetime,
    ) -> int:
        count = 0
        for page_id, page in tuple(self._tx.state.memory_pages.items()):
            if source_event_id in page.source_event_ids and not page.needs_rebuild:
                self._tx.state.memory_pages[page_id] = replace(
                    page,
                    needs_rebuild=True,
                    updated_at=updated_at,
                )
                count += 1
        return count


class InMemoryMemoryPageVersionRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def record(self, version: MemoryPageVersion) -> MemoryPageVersion:
        key = (version.page_id, version.version)
        existing_id = self._tx.state.memory_page_version_by_page_version.get(key)
        if existing_id is not None:
            return self._tx.state.memory_page_versions[existing_id]

        self._tx.state.memory_page_versions[version.id] = version
        self._tx.state.memory_page_version_by_page_version[key] = version.id
        return version


class InMemoryGraphWriteJobRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def enqueue(self, job: GraphWriteJob) -> GraphWriteJob:
        existing_id = self._tx.state.graph_job_by_idempotency_key.get(job.idempotency_key)
        if existing_id is not None:
            return self._tx.state.graph_write_jobs[existing_id]

        self._tx.state.graph_write_jobs[job.id] = job
        self._tx.state.graph_job_by_idempotency_key[job.idempotency_key] = job.id
        return job

    async def claim_pending(
        self,
        *,
        now: datetime,
        worker_id: str,
        lock_duration: timedelta,
        limit: int,
    ) -> tuple[GraphWriteJob, ...]:
        eligible = [
            job
            for job in self._tx.state.graph_write_jobs.values()
            if _is_graph_job_claimable(job, now)
        ]
        eligible.sort(
            key=lambda job: (
                0 if job.status == "pending" else 1,
                job.next_run_at,
                -job.priority,
                job.created_at,
            )
        )

        claimed: list[GraphWriteJob] = []
        for job in eligible[:limit]:
            updated = replace(
                job,
                status="processing",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + lock_duration,
                updated_at=now,
            )
            self._tx.state.graph_write_jobs[job.id] = updated
            claimed.append(updated)
        return tuple(claimed)

    async def mark_succeeded(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
    ) -> GraphWriteJob:
        job = self._get_locked_job(job_id, locked_by)
        updated = replace(
            job,
            status="succeeded",
            locked_at=None,
            locked_by=None,
            lock_expires_at=None,
            last_error=None,
            updated_at=now,
        )
        self._tx.state.graph_write_jobs[job_id] = updated
        return updated

    async def mark_failed(
        self,
        *,
        job_id: str,
        locked_by: str,
        now: datetime,
        error: str,
        retry_delay: timedelta,
    ) -> GraphWriteJob:
        job = self._get_locked_job(job_id, locked_by)
        attempts = job.attempts + 1
        if attempts >= job.max_attempts:
            updated = replace(
                job,
                status="dead_letter",
                attempts=attempts,
                locked_at=None,
                locked_by=None,
                lock_expires_at=None,
                last_error=error,
                dead_letter_reason=error,
                updated_at=now,
            )
        else:
            updated = replace(
                job,
                status="pending",
                attempts=attempts,
                next_run_at=now + retry_delay,
                locked_at=None,
                locked_by=None,
                lock_expires_at=None,
                last_error=error,
                updated_at=now,
            )
        self._tx.state.graph_write_jobs[job_id] = updated
        return updated

    def _get_locked_job(self, job_id: str, locked_by: str) -> GraphWriteJob:
        job = self._tx.state.graph_write_jobs[job_id]
        if job.status != "processing" or job.locked_by != locked_by:
            raise OutboxLockOwnershipError("graph write job is not locked by this worker")
        return job


class InMemoryMemoryGraphLinkRepository:
    def __init__(self, tx: InMemoryTransactionView) -> None:
        self._tx = tx

    async def upsert(self, link: MemoryGraphLink) -> MemoryGraphLink:
        key = (
            link.backend,
            link.backend_object_type,
            link.backend_object_id,
            link.memory_id,
            link.link_type,
        )
        existing_id = self._tx.state.memory_graph_link_by_backend_object.get(key)
        if existing_id is not None:
            return self._tx.state.memory_graph_links[existing_id]

        self._tx.state.memory_graph_links[link.id] = link
        self._tx.state.memory_graph_link_by_backend_object[key] = link.id
        return link

    async def list_by_memory(self, memory_id: str) -> tuple[MemoryGraphLink, ...]:
        return tuple(
            link
            for link in self._tx.state.memory_graph_links.values()
            if link.memory_id == memory_id
        )


def _is_graph_job_claimable(job: GraphWriteJob, now: datetime) -> bool:
    if job.status == "pending" and job.next_run_at <= now:
        return True
    return (
        job.status == "processing"
        and job.lock_expires_at is not None
        and job.lock_expires_at <= now
    )
