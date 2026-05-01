from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from memwing.application.failure_semantics import classify_failure
from memwing.core.forgetting_curve import compute_decayed_score, effective_last_touched_at
from memwing.core.memory_search import (
    MemorySearchQuery,
    MemorySearchResult,
    MemorySearchResultItem,
)
from memwing.core.models import (
    MemoryItem,
    MemoryStatus,
    PageMemory,
    SourceEvent,
    WorkingMemoryEntry,
)
from memwing.core.scope import EffectiveScope
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort


_CURRENT_RECALL_STATUSES = frozenset((MemoryStatus.ACTIVE,))
LocalBranchResultT = TypeVar("LocalBranchResultT")


@dataclass(frozen=True, slots=True)
class CurrentTruthWarning:
    branch: str
    reason_code: str
    message: str


@dataclass(frozen=True, slots=True)
class CurrentTruthResult:
    working_memory: tuple[MemorySearchResultItem, ...]
    current_facts: tuple[MemorySearchResultItem, ...]
    background: tuple[MemorySearchResultItem, ...]
    supporting_evidence: tuple[MemorySearchResultItem, ...]
    raw_events: tuple[MemorySearchResultItem, ...]
    warnings: tuple[CurrentTruthWarning, ...]
    trace_id: str


class CurrentTruthModule:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        graph_backend: GraphBackendPort | None = None,
        evidence_index: EvidenceIndexPort | None = None,
        now: Callable[[], datetime] | None = None,
        graph_timeout: timedelta = timedelta(seconds=2),
        evidence_timeout: timedelta = timedelta(seconds=2),
        local_timeout: timedelta = timedelta(seconds=2),
    ) -> None:
        self._unit_of_work = unit_of_work
        self._graph_backend = graph_backend
        self._evidence_index = evidence_index
        self._now = now or (lambda: datetime.now(UTC))
        self._graph_timeout = graph_timeout
        self._evidence_timeout = evidence_timeout
        self._local_timeout = local_timeout

    async def recall_current(self, query: MemorySearchQuery) -> CurrentTruthResult:
        (
            (graph_result, graph_warning),
            (evidence_result, evidence_warning),
            (working_memory, working_warning),
            (memory_items, memory_items_warning),
            (page_memory, page_warning),
            (raw_events, raw_warning),
        ) = await asyncio.gather(
            self._graph_current(query),
            self._evidence(query),
            self._working_memory(query),
            self._memory_items(query),
            self._page_memory(query),
            self._raw_events(query),
        )

        warnings = tuple(
            warning
            for warning in (
                graph_warning,
                evidence_warning,
                working_warning,
                memory_items_warning,
                page_warning,
                raw_warning,
            )
            if warning is not None
        )
        current_facts = (
            *_current_graph_items(graph_result),
            *memory_items,
        )
        return CurrentTruthResult(
            working_memory=working_memory,
            current_facts=tuple(current_facts[: query.limit]),
            background=page_memory,
            supporting_evidence=evidence_result.results if evidence_result is not None else (),
            raw_events=raw_events,
            warnings=warnings,
            trace_id=query.trace_id or "current_truth:recall_current",
        )

    async def _graph_current(
        self,
        query: MemorySearchQuery,
    ) -> tuple[MemorySearchResult | None, CurrentTruthWarning | None]:
        if self._graph_backend is None:
            return None, None
        try:
            result = await asyncio.wait_for(
                self._graph_backend.search_current(query),
                timeout=self._graph_timeout.total_seconds(),
            )
        except Exception as exc:
            failure = classify_failure(exc, audit_stage="current_truth.graph")
            return None, CurrentTruthWarning(
                branch="graph_backend",
                reason_code=failure.reason_code,
                message=failure.safe_message,
            )
        return result, None

    async def _evidence(
        self,
        query: MemorySearchQuery,
    ) -> tuple[MemorySearchResult | None, CurrentTruthWarning | None]:
        if self._evidence_index is None:
            return None, None
        try:
            result = await asyncio.wait_for(
                self._evidence_index.search(query),
                timeout=self._evidence_timeout.total_seconds(),
            )
        except Exception as exc:
            failure = classify_failure(exc, audit_stage="current_truth.evidence")
            return None, CurrentTruthWarning(
                branch="evidence_index",
                reason_code=failure.reason_code,
                message=failure.safe_message,
            )
        return result, None

    async def _working_memory(
        self,
        query: MemorySearchQuery,
    ) -> tuple[tuple[MemorySearchResultItem, ...], CurrentTruthWarning | None]:
        try:
            entries = await self._run_local_branch(
                self._load_working_memory(query),
            )
        except Exception as exc:
            return (), _branch_warning("working_memory", exc)
        return tuple(_working_memory_to_result_item(entry) for entry in entries), None

    async def _memory_items(
        self,
        query: MemorySearchQuery,
    ) -> tuple[tuple[MemorySearchResultItem, ...], CurrentTruthWarning | None]:
        try:
            memory_items = await self._run_local_branch(
                self._load_memory_items(query),
            )
        except Exception as exc:
            return (), _branch_warning("memory_items", exc)

        ranked_items = _rank_memory_items(
            query=query.query,
            items=memory_items,
            min_score=query.min_score,
            now=self._now(),
        )
        return (
            tuple(
                _memory_item_to_result_item(item, score=score)
                for item, score in ranked_items[: query.limit]
            ),
            None,
        )

    async def _page_memory(
        self,
        query: MemorySearchQuery,
    ) -> tuple[tuple[MemorySearchResultItem, ...], CurrentTruthWarning | None]:
        try:
            page = await self._run_local_branch(self._load_page_memory(query))
        except Exception as exc:
            return (), _branch_warning("page_memory", exc)
        return (() if page is None else (_page_memory_to_result_item(page),)), None

    async def _raw_events(
        self,
        query: MemorySearchQuery,
    ) -> tuple[tuple[MemorySearchResultItem, ...], CurrentTruthWarning | None]:
        try:
            events = await self._run_local_branch(self._load_raw_events(query))
        except Exception as exc:
            return (), _branch_warning("raw_events", exc)
        return tuple(_source_event_to_result_item(event) for event in events), None

    async def _run_local_branch(
        self,
        operation: Awaitable[LocalBranchResultT],
    ) -> LocalBranchResultT:
        return await asyncio.wait_for(operation, timeout=self._local_timeout.total_seconds())

    async def _load_working_memory(
        self,
        query: MemorySearchQuery,
    ) -> tuple[WorkingMemoryEntry, ...]:
        async with self._unit_of_work.transaction() as tx:
            return await tx.working_memory_entries.list_recent(
                project_memory_space_id=query.scope.project_memory_space_id,
                thread_id=query.scope.thread_id,
                limit=query.limit,
            )

    async def _load_memory_items(self, query: MemorySearchQuery) -> tuple[MemoryItem, ...]:
        async with self._unit_of_work.transaction() as tx:
            return await tx.memory_items.list_for_scope(
                scope=query.scope,
                limit=max(query.limit * 4, query.limit),
            )

    async def _load_page_memory(self, query: MemorySearchQuery) -> PageMemory | None:
        async with self._unit_of_work.transaction() as tx:
            return await _load_page_memory(tx.memory_pages, query)

    async def _load_raw_events(self, query: MemorySearchQuery) -> tuple[SourceEvent, ...]:
        async with self._unit_of_work.transaction() as tx:
            events = await tx.source_events.list_recent_for_scope(
                scope=query.scope,
                limit=query.limit,
            )
            uncovered_events: list[SourceEvent] = []
            for event in events:
                linked_items = await tx.memory_items.list_by_source_event(event.id)
                if any(_memory_item_covers_source_event(item, query) for item in linked_items):
                    continue
                uncovered_events.append(event)
            return tuple(uncovered_events)


async def _load_page_memory(repository: object, query: MemorySearchQuery) -> PageMemory | None:
    if query.scope.thread_id is not None:
        return await repository.get_by_scope(
            project_memory_space_id=query.scope.project_memory_space_id,
            scope_type="thread",
            scope_id=query.scope.thread_id,
        )
    if query.scope.group_ids is not None and len(query.scope.group_ids) == 1:
        return await repository.get_by_scope(
            project_memory_space_id=query.scope.project_memory_space_id,
            scope_type="group",
            scope_id=query.scope.group_ids[0],
        )
    return await repository.get_by_scope(
        project_memory_space_id=query.scope.project_memory_space_id,
        scope_type="project",
        scope_id=query.scope.project_memory_space_id,
    )


def _current_graph_items(result: MemorySearchResult | None) -> tuple[MemorySearchResultItem, ...]:
    if result is None:
        return ()
    return tuple(item for item in result.results if item.valid_to is None)


def _branch_warning(branch: str, exc: BaseException) -> CurrentTruthWarning:
    failure = classify_failure(exc, audit_stage=f"current_truth.{branch}")
    return CurrentTruthWarning(
        branch=branch,
        reason_code=failure.reason_code,
        message=failure.safe_message,
    )


def _rank_memory_items(
    *,
    query: str,
    items: tuple[MemoryItem, ...],
    min_score: float,
    now: datetime,
) -> list[tuple[MemoryItem, float]]:
    ranked: list[tuple[MemoryItem, float]] = []
    for item in items:
        if not _is_current_recallable(item):
            continue
        score = _memory_item_score(item, now=now)
        if score < min_score:
            continue
        if query and not _matches_query(item, query):
            continue
        ranked.append((item, score))
    return sorted(ranked, key=lambda pair: (pair[1], pair[0].updated_at, pair[0].id), reverse=True)


def _is_current_recallable(item: MemoryItem) -> bool:
    return (
        item.status in _CURRENT_RECALL_STATUSES
        and item.removed_at is None
        and item.hidden_at is None
        and item.invalidated_at is None
        and item.valid_to is None
    )


def _memory_item_covers_source_event(item: MemoryItem, query: MemorySearchQuery) -> bool:
    if not _memory_item_in_scope(item, query.scope):
        return False
    if item.status in (MemoryStatus.HIDDEN, MemoryStatus.INVALID, MemoryStatus.REMOVED):
        return False
    if item.removed_at is not None or item.hidden_at is not None:
        return False
    if item.invalidated_at is not None or item.valid_to is not None:
        return False
    return True


def _memory_item_in_scope(item: MemoryItem, scope: EffectiveScope) -> bool:
    return (
        item.project_memory_space_id == scope.project_memory_space_id
        and (scope.thread_id is None or item.thread_id == scope.thread_id)
        and (scope.group_ids is None or item.group_id in scope.group_ids)
        and (scope.shared_group_id is None or item.shared_group_id == scope.shared_group_id)
    )


def _memory_item_score(item: MemoryItem, *, now: datetime) -> float:
    if item.cached_decayed_score is not None:
        return item.cached_decayed_score
    return compute_decayed_score(
        original_score=item.original_score,
        effective_last_touched_at=effective_last_touched_at(item),
        now=now,
        half_life_days=item.half_life_days,
    )


def _matches_query(item: MemoryItem, query: str) -> bool:
    normalized_query = query.casefold()
    searchable = " ".join(
        text for text in (item.title, item.content, item.summary) if text is not None
    ).casefold()
    return normalized_query in searchable


def _memory_item_to_result_item(item: MemoryItem, *, score: float) -> MemorySearchResultItem:
    return MemorySearchResultItem(
        id=item.id,
        text=item.content,
        score=score,
        source="memory_item",
        source_event_ids=item.source_event_ids,
        memory_item_ids=(item.id,),
        valid_from=item.valid_from,
        valid_to=item.valid_to,
        metadata={
            "title": item.title,
            "status": item.status.value,
            "route": item.route.value,
            "display_type": item.display_type.value,
            "summary": item.summary,
        },
    )


def _working_memory_to_result_item(entry: WorkingMemoryEntry) -> MemorySearchResultItem:
    return MemorySearchResultItem(
        id=entry.id,
        text=entry.content,
        score=None,
        source="working_memory",
        source_event_ids=(entry.source_event_id,),
        memory_item_ids=(),
        valid_from=entry.created_at,
        valid_to=entry.flushed_at,
        metadata={"sequence": entry.sequence},
    )


def _page_memory_to_result_item(page: PageMemory) -> MemorySearchResultItem:
    return MemorySearchResultItem(
        id=page.id,
        text=page.brief,
        score=None,
        source="page_memory",
        source_event_ids=page.source_event_ids,
        memory_item_ids=page.linked_memory_item_ids,
        valid_from=page.created_at,
        valid_to=None,
        metadata={
            "title": page.title,
            "scope_type": page.scope_type,
            "scope_id": page.scope_id,
            "needs_rebuild": page.needs_rebuild,
        },
    )


def _source_event_to_result_item(event: SourceEvent) -> MemorySearchResultItem:
    return MemorySearchResultItem(
        id=event.id,
        text=event.content_preview or event.content,
        score=None,
        source="raw_event",
        source_event_ids=(event.id,),
        memory_item_ids=(),
        valid_from=event.event_time,
        valid_to=None,
        metadata={
            "source": "raw_event",
            "source_type": event.source_type,
            "author_id": event.author_id,
            "raw_payload_hash": event.raw_payload_hash,
            "graph_backend_raw_retained": event.graph_backend_raw_retained,
        },
    )
