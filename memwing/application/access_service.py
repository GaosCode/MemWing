from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from memwing.api.agent_context import AgentContextRequest, AgentContextResult
from memwing.api.agent_knowledge import (
    AgentKnowledgeExplainRequest,
    AgentKnowledgeExplainResult,
    AgentKnowledgeGetRequest,
    AgentKnowledgeGetResult,
)
from memwing.api.agent_memory import AgentMemoryQuery, AgentMemoryResultItem, AgentMemorySearchResult
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.forgetting_curve import compute_decayed_score, effective_last_touched_at
from memwing.core.models import MemoryItem, MemoryStatus, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.ports.event_store import EventStoreUnitOfWorkPort


_CURRENT_RECALL_STATUSES = frozenset((MemoryStatus.ACTIVE,))
_HISTORY_RECALL_STATUSES = frozenset(
    (
        MemoryStatus.CANDIDATE,
        MemoryStatus.ACTIVE,
        MemoryStatus.FADING,
        MemoryStatus.ARCHIVED,
        MemoryStatus.INVALID,
        MemoryStatus.NEEDS_REVIEW,
    )
)


class MemoryAccessService:
    def __init__(
        self,
        scope_resolver: ScopeResolver,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._scope_resolver = scope_resolver
        self._unit_of_work = unit_of_work
        self._now = now or (lambda: datetime.now(UTC))

    async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
        resolved = await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        query_text = request.prompt or "current memory"
        async with self._unit_of_work.transaction() as tx:
            items = await tx.memory_items.list_for_scope(
                scope=resolved.effective_scope,
                limit=8,
            )
        results = _rank_memory_items(
            query=query_text,
            items=items,
            mode="current",
            min_score=0,
            now=self._now(),
        )
        context_blocks = tuple(
            {
                "type": "memory_item",
                "id": item.id,
                "title": item.title,
                "content": item.content,
                "source_event_ids": item.source_event_ids,
            }
            for item, _score in results
        )
        return AgentContextResult(
            messages=None,
            system_prompt_addition=None,
            context_blocks=context_blocks,
            estimated_tokens=None,
            trace_id=_trace_id("context", request.runtime_ref.agent_id),
        )

    async def search(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        resolved = await self._scope_resolver.resolve_runtime(query.runtime_ref, query.scope)
        async with self._unit_of_work.transaction() as tx:
            items = await tx.memory_items.list_for_scope(
                scope=resolved.effective_scope,
                limit=max(query.limit * 4, query.limit),
            )
        ranked = _rank_memory_items(
            query=query.query,
            items=items,
            mode=query.mode,
            min_score=query.min_score,
            now=self._now(),
        )
        ranked = _sort_ranked_items(ranked, sort=query.sort)
        results = tuple(
            _memory_item_to_result_item(item, score=score)
            for item, score in ranked[: query.limit]
        )
        return AgentMemorySearchResult(
            contexts=tuple(item.text for item in results),
            results=results,
            next_cursor=None,
            trace_id=_trace_id("search", query.runtime_ref.agent_id),
        )

    async def get(self, request: AgentKnowledgeGetRequest) -> AgentKnowledgeGetResult:
        resolved = await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        async with self._unit_of_work.transaction() as tx:
            memory_item = await tx.memory_items.get(request.memory_id)
            if memory_item is None or not _memory_item_in_scope(
                memory_item,
                resolved.effective_scope,
            ):
                memory_item = None
                source_events: tuple[SourceEvent, ...] = ()
            elif request.include_evidence:
                loaded_source_events: list[SourceEvent] = []
                for source_event_id in memory_item.source_event_ids:
                    event = await tx.source_events.get_source_event(source_event_id)
                    if event is not None:
                        loaded_source_events.append(event)
                source_events = tuple(loaded_source_events)
            else:
                source_events = ()
        return AgentKnowledgeGetResult(
            item=(
                _memory_item_to_result_item(
                    memory_item,
                    score=_memory_item_score(memory_item, now=self._now()),
                )
                if memory_item is not None
                else None
            ),
            evidence=tuple(
                _source_event_to_result_item(event, memory_id=request.memory_id)
                for event in source_events
            ),
            trace_id=_trace_id("get", request.runtime_ref.agent_id),
        )

    async def explain(self, request: AgentKnowledgeExplainRequest) -> AgentKnowledgeExplainResult:
        resolved = await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        async with self._unit_of_work.transaction() as tx:
            memory_item = await tx.memory_items.get(request.memory_id)
        if memory_item is None or not _memory_item_in_scope(memory_item, resolved.effective_scope):
            source_event_ids: tuple[str, ...] = ()
            rationale = "No indexed memory record is available for this id."
        else:
            source_event_ids = memory_item.source_event_ids
            score = _memory_item_score(memory_item, now=self._now())
            rationale = (
                f"Memory {memory_item.id} is {memory_item.status.value}, "
                f"route={memory_item.route.value}, score={score:.3f}, "
                f"sources={len(memory_item.source_event_ids)}."
            )
        return AgentKnowledgeExplainResult(
            memory_id=request.memory_id,
            source_event_ids=source_event_ids,
            rationale=rationale,
            trace_id=_trace_id("explain", request.runtime_ref.agent_id),
        )


def _trace_id(operation: str, agent_id: str) -> str:
    return f"memory_access:{operation}:{agent_id}"


def _rank_memory_items(
    *,
    query: str,
    items: tuple[MemoryItem, ...],
    mode: str,
    min_score: float,
    now: datetime,
) -> list[tuple[MemoryItem, float]]:
    ranked: list[tuple[MemoryItem, float]] = []
    for item in items:
        if not _is_recallable(item, mode=mode):
            continue
        score = _memory_item_score(item, now=now)
        if score < min_score:
            continue
        if query and not _matches_query(item, query):
            if mode == "current":
                continue
            score *= 0.5
        ranked.append((item, score))
    return ranked


def _sort_ranked_items(
    ranked: list[tuple[MemoryItem, float]],
    *,
    sort: str,
) -> list[tuple[MemoryItem, float]]:
    if sort == "event_time":
        return sorted(
            ranked,
            key=lambda pair: (pair[0].event_time or pair[0].updated_at, pair[0].id),
            reverse=True,
        )
    if sort == "updated_at":
        return sorted(ranked, key=lambda pair: (pair[0].updated_at, pair[0].id), reverse=True)
    return sorted(ranked, key=lambda pair: (pair[1], pair[0].updated_at, pair[0].id), reverse=True)


def _is_recallable(item: MemoryItem, *, mode: str) -> bool:
    if item.removed_at is not None or item.status is MemoryStatus.HIDDEN:
        return False
    if mode == "history":
        return item.status in _HISTORY_RECALL_STATUSES
    return item.status in _CURRENT_RECALL_STATUSES


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


def _memory_item_in_scope(item: MemoryItem, scope: EffectiveScope) -> bool:
    if item.project_memory_space_id != scope.project_memory_space_id:
        return False
    if scope.thread_id is not None and item.thread_id != scope.thread_id:
        return False
    if scope.group_ids is not None and item.group_id not in scope.group_ids:
        return False
    if scope.shared_group_id is not None and item.shared_group_id != scope.shared_group_id:
        return False
    return True


def _memory_item_to_result_item(
    item: MemoryItem,
    *,
    score: float,
) -> AgentMemoryResultItem:
    return AgentMemoryResultItem(
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


def _source_event_to_result_item(
    event: SourceEvent,
    *,
    memory_id: str,
) -> AgentMemoryResultItem:
    return AgentMemoryResultItem(
        id=event.id,
        text=event.content_preview or event.content,
        score=None,
        source="evidence",
        source_event_ids=(event.id,),
        memory_item_ids=(memory_id,),
        valid_from=event.event_time,
        valid_to=None,
        metadata={
            "source_type": event.source_type,
            "author_id": event.author_id,
            "graph_backend_raw_retained": event.graph_backend_raw_retained,
        },
    )
