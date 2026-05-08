from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from memwing.application.current_truth import CurrentTruthModule
from memwing.application.current_truth_read_model import current_truth_to_access_result
from memwing.application.decision_card_service import DecisionCardCommand, DecisionCardService
from memwing.application.memory_item_ranking import (
    memory_item_score,
    rank_memory_items,
    sort_ranked_items,
)
from memwing.application.memory_access_audit import record_recall_events, trace_id
from memwing.application.memory_access_read_model import (
    memory_item_in_scope,
    memory_item_to_result_item,
    paginate_items,
    result_fetch_limit,
    search_graph_history,
    source_event_in_scope,
    source_event_to_result_item,
)
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.memory_access import (
    MemoryAccessExplainRequest,
    MemoryAccessExplainResult,
    MemoryAccessGetRequest,
    MemoryAccessGetResult,
    MemoryAccessQuery,
    MemoryAccessSearchResult,
)
from memwing.core.memory_search import MemorySearchQuery
from memwing.core.models import PushCandidate, SourceEvent
from memwing.core.runtime import AgentContextRequest, AgentContextResult
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort


class MemoryAccessService:
    def __init__(
        self,
        scope_resolver: ScopeResolver,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        current_truth: CurrentTruthModule | None = None,
        graph_backend: GraphBackendPort | None = None,
        evidence_index: EvidenceIndexPort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._scope_resolver = scope_resolver
        self._unit_of_work = unit_of_work
        self._graph_backend = graph_backend
        self._evidence_index = evidence_index
        self._current_truth = current_truth or CurrentTruthModule(
            unit_of_work,
            graph_backend=graph_backend,
            evidence_index=evidence_index,
            now=now,
        )
        self._decision_cards = DecisionCardService(unit_of_work)
        self._now = now or (lambda: datetime.now(UTC))

    async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
        resolved = await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        query_text = request.prompt or "current memory"
        current = await self._current_truth.recall_current(
            MemorySearchQuery(
                query=query_text,
                scope=resolved.effective_scope,
                limit=8,
                trace_id=trace_id("context", request.runtime_ref.agent_id),
            )
        )
        result = current_truth_to_access_result(current, limit=8)
        context_blocks = tuple(
            {
                "type": item.source,
                "id": item.id,
                "title": item.metadata.get("title"),
                "content": item.text,
                "source_event_ids": item.source_event_ids,
            }
            for item in result.results
        )
        return AgentContextResult(
            messages=None,
            system_prompt_addition=None,
            context_blocks=context_blocks,
            estimated_tokens=None,
            trace_id=trace_id("context", request.runtime_ref.agent_id),
        )

    async def search(self, query: MemoryAccessQuery) -> MemoryAccessSearchResult:
        resolved = await self._scope_resolver.resolve_runtime(query.runtime_ref, query.scope)
        if query.mode == "current":
            current_trace_id = trace_id("search", query.runtime_ref.agent_id)
            fetch_limit = result_fetch_limit(query)
            current = await self._current_truth.recall_current(
                MemorySearchQuery(
                    query=query.query,
                    scope=resolved.effective_scope,
                    mode="current",
                    limit=fetch_limit,
                    cursor=None,
                    sort=query.sort,
                    min_score=query.min_score,
                    trace_id=current_trace_id,
                )
            )
            result = current_truth_to_access_result(
                current,
                limit=query.limit,
                cursor=query.cursor,
                sort=query.sort,
                query=query.query,
            )
            await record_recall_events(
                self._unit_of_work,
                result=result,
                query_text=query.query,
                project_memory_space_id=resolved.effective_scope.project_memory_space_id,
                trace_id=current_trace_id,
                now=self._now(),
            )
            return result

        if query.mode == "history" and self._graph_backend is not None:
            history_result = await search_graph_history(
                graph_backend=self._graph_backend,
                evidence_index=self._evidence_index,
                query=query,
                scope=resolved.effective_scope,
                trace_id=trace_id("search", query.runtime_ref.agent_id),
            )
            if history_result is not None:
                return history_result

        async with self._unit_of_work.transaction() as tx:
            fetch_limit = result_fetch_limit(query)
            items = await tx.memory_items.list_for_scope(
                scope=resolved.effective_scope,
                limit=max(fetch_limit * 4, fetch_limit),
            )
        ranked = rank_memory_items(
            query=query.query,
            items=items,
            mode=query.mode,
            min_score=query.min_score,
            now=self._now(),
        )
        ranked = sort_ranked_items(ranked, sort=query.sort)
        ranked_results = tuple(
            memory_item_to_result_item(item, score=score)
            for item, score in ranked
        )
        results, next_cursor = paginate_items(
            ranked_results,
            limit=query.limit,
            cursor=query.cursor,
        )
        return MemoryAccessSearchResult(
            contexts=tuple(item.text for item in results),
            results=results,
            next_cursor=next_cursor,
            trace_id=trace_id("search", query.runtime_ref.agent_id),
        )

    async def get(self, request: MemoryAccessGetRequest) -> MemoryAccessGetResult:
        resolved = await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        async with self._unit_of_work.transaction() as tx:
            memory_item = await tx.memory_items.get(request.memory_id)
            if memory_item is None or not memory_item_in_scope(
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
        return MemoryAccessGetResult(
            item=(
                memory_item_to_result_item(
                    memory_item,
                    score=memory_item_score(memory_item, now=self._now()),
                )
                if memory_item is not None
                else None
            ),
            evidence=tuple(
                source_event_to_result_item(event, memory_id=request.memory_id)
                for event in source_events
            ),
            trace_id=trace_id("get", request.runtime_ref.agent_id),
        )

    async def explain(self, request: MemoryAccessExplainRequest) -> MemoryAccessExplainResult:
        resolved = await self._scope_resolver.resolve_runtime(request.runtime_ref, request.scope)
        async with self._unit_of_work.transaction() as tx:
            memory_item = await tx.memory_items.get(request.memory_id)
            source_events: tuple[SourceEvent, ...] = ()
            graph_links = ()
            if memory_item is not None and memory_item_in_scope(
                memory_item,
                resolved.effective_scope,
            ):
                loaded_source_events: list[SourceEvent] = []
                for source_event_id in memory_item.source_event_ids:
                    event = await tx.source_events.get_source_event(source_event_id)
                    if event is not None and source_event_in_scope(event, resolved.effective_scope):
                        loaded_source_events.append(event)
                source_events = tuple(loaded_source_events)
                graph_links = await tx.memory_graph_links.list_by_memory(memory_item.id)
        if memory_item is None or not memory_item_in_scope(memory_item, resolved.effective_scope):
            source_event_ids: tuple[str, ...] = ()
            rationale = "No indexed memory record is available for this id."
        else:
            source_event_ids = memory_item.source_event_ids
            score = memory_item_score(memory_item, now=self._now())
            graph_backend_raw_retained = any(
                event.graph_backend_raw_retained for event in source_events
            )
            rationale = (
                f"Memory {memory_item.id} is {memory_item.status.value}, "
                f"route={memory_item.route.value}, score={score:.3f}, "
                f"source_events={len(source_events)}, graph_links={len(graph_links)}, "
                f"graph_backend_raw_retained={str(graph_backend_raw_retained).lower()}."
            )
        return MemoryAccessExplainResult(
            memory_id=request.memory_id,
            source_event_ids=source_event_ids,
            rationale=rationale,
            trace_id=trace_id("explain", request.runtime_ref.agent_id),
        )

    async def create_decision_card(self, command: DecisionCardCommand) -> PushCandidate:
        return await self._decision_cards.create_for_memory(command)
