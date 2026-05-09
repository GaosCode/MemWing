from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
import sys
from time import perf_counter
from typing import Protocol

from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult
from memwing.core.models import GraphWriteResult
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.graph.graphiti_cache_context import graphiti_model_cache_context
from memwing.infrastructure.graph.graphiti_direct_preseed import _direct_preseed_memory_item
from memwing.infrastructure.graph.graphiti_result_mapping import (
    _edge_to_result_item,
    _graph_write_result_from_graphiti_result,
)
from memwing.infrastructure.graph.graphiti_safety import (
    _blocked_batch_results,
    _elapsed_ms,
    _graphiti_group_id,
    _graph_write_request_order,
    _raw_episode,
    _safe_error_message,
    _stable_graphiti_episode_uuid,
)
from memwing.ports.graph_backend import (
    GraphFactPreseedItemResult,
    GraphFactPreseedRequest,
    GraphFactPreseedResult,
    GraphWriteBatchItemResult,
    GraphWriteBatchRequest,
    GraphWriteBatchResult,
    GraphWriteRequest,
)


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_handler)
logger.propagate = False


class GraphitiRuntime(Protocol):
    async def add_episode(self, **kwargs: object) -> object:
        ...

    async def search(
        self,
        query: str,
        group_ids: list[str],
        num_results: int,
    ) -> Sequence[object]:
        ...


GraphitiFactory = Callable[..., GraphitiRuntime]


@dataclass(frozen=True, slots=True)
class GraphitiConnectionConfig:
    uri: str
    user: str | None = None
    password: str | None = None
    store_raw_episode_content: bool = True
    semantic_bulk_ingest_enabled: bool = False


class GraphitiAdapter:
    def __init__(
        self,
        graphiti: GraphitiRuntime,
        *,
        semantic_bulk_ingest_enabled: bool = False,
        cache_metrics_sources: tuple[object, ...] = (),
    ) -> None:
        self._graphiti = graphiti
        self._semantic_bulk_ingest_enabled = semantic_bulk_ingest_enabled
        self._cache_metrics_sources = cache_metrics_sources

    @classmethod
    def from_clients(
        cls,
        config: GraphitiConnectionConfig,
        *,
        llm_client: object,
        embedder: object,
        cross_encoder: object,
        graphiti_factory: GraphitiFactory | None = None,
    ) -> GraphitiAdapter:
        if llm_client is None or embedder is None or cross_encoder is None:
            raise ValueError("GraphitiAdapter requires llm_client, embedder, and cross_encoder")

        factory = graphiti_factory or _load_graphiti_factory()
        graphiti = factory(
            uri=config.uri,
            user=config.user,
            password=config.password,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
            store_raw_episode_content=config.store_raw_episode_content,
        )
        return cls(
            graphiti,
            semantic_bulk_ingest_enabled=config.semantic_bulk_ingest_enabled,
            cache_metrics_sources=(llm_client, embedder),
        )

    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        return await self._search(query, trace_suffix="current")

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        return await self._search(query, trace_suffix="history")

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        return await self._ingest_one(request, previous_episode_uuid=None)

    async def ingest_graph_jobs(self, request: GraphWriteBatchRequest) -> GraphWriteBatchResult:
        started = perf_counter()
        logger.info(
            "graphiti_adapter.ingest_batch_started job_count=%s semantic_bulk=%s",
            len(request.requests),
            self._semantic_bulk_ingest_enabled,
        )
        bulk_ingest = (
            getattr(self._graphiti, "add_episode_bulk_semantic", None)
            if self._semantic_bulk_ingest_enabled
            else None
        )
        if bulk_ingest is not None:
            result = await self._ingest_graph_jobs_bulk(request, bulk_ingest=bulk_ingest)
            logger.info(
                "graphiti_adapter.ingest_batch_completed job_count=%s item_count=%s "
                "semantic_bulk=true duration_ms=%.1f",
                len(request.requests),
                len(result.items),
                _elapsed_ms(started),
            )
            return result

        items: list[GraphWriteBatchItemResult] = []
        previous_episode_uuid: str | None = None
        blocked_reason: str | None = None
        ordered_requests = tuple(sorted(request.requests, key=_graph_write_request_order))
        for index, graph_request in enumerate(ordered_requests, start=1):
            if blocked_reason is not None:
                items.append(
                    GraphWriteBatchItemResult(
                        job_id=graph_request.job.id,
                        result=None,
                        error_type="GraphitiOrderedBatchBlocked",
                        error_message=None,
                        reason_code=blocked_reason,
                        retryable=True,
                    )
                )
                continue
            try:
                episode_started = perf_counter()
                logger.info(
                    "graphiti_adapter.episode_started job_id=%s memory_id=%s index=%s/%s "
                    "project_memory_space_id=%s previous_episode=%s",
                    graph_request.job.id,
                    graph_request.memory_item.id,
                    index,
                    len(ordered_requests),
                    graph_request.job.project_memory_space_id,
                    bool(previous_episode_uuid),
                )
                result = await self._ingest_one(
                    graph_request,
                    previous_episode_uuid=previous_episode_uuid,
                )
            except Exception as exc:
                logger.info(
                    "graphiti_adapter.episode_failed job_id=%s index=%s/%s duration_ms=%.1f "
                    "error_type=%s error_message=%r",
                    graph_request.job.id,
                    index,
                    len(ordered_requests),
                    _elapsed_ms(episode_started),
                    exc.__class__.__name__,
                    _safe_error_message(exc),
                )
                items.append(
                    GraphWriteBatchItemResult(
                        job_id=graph_request.job.id,
                        result=None,
                        error_type=exc.__class__.__name__,
                        error_message=_safe_error_message(exc),
                        reason_code="graphiti_ordered_episode_failed",
                        retryable=True,
                    )
                )
                blocked_reason = "graphiti_ordered_episode_blocked"
                continue

            if result.backend_episode_refs:
                previous_episode_uuid = result.backend_episode_refs[-1]
            logger.info(
                "graphiti_adapter.episode_completed job_id=%s index=%s/%s episode_ref_count=%s "
                "fact_count=%s invalidated_fact_count=%s duration_ms=%.1f",
                graph_request.job.id,
                index,
                len(ordered_requests),
                len(result.backend_episode_refs),
                len(result.facts),
                len(result.invalidated_facts),
                _elapsed_ms(episode_started),
            )
            items.append(
                GraphWriteBatchItemResult(
                    job_id=graph_request.job.id,
                    result=result,
                    error_type=None,
                    error_message=None,
                    reason_code=None,
                    retryable=False,
                )
            )
        result = GraphWriteBatchResult(items=tuple(items))
        logger.info(
            "graphiti_adapter.ingest_batch_completed job_count=%s item_count=%s "
            "semantic_bulk=false duration_ms=%.1f",
            len(request.requests),
            len(result.items),
            _elapsed_ms(started),
        )
        return result

    async def preseed_facts(self, request: GraphFactPreseedRequest) -> GraphFactPreseedResult:
        driver = getattr(self._graphiti, "driver", None)
        embedder = getattr(self._graphiti, "embedder", None)
        if driver is None or embedder is None:
            raise NotImplementedError("direct graph preseed requires Graphiti driver and embedder")

        source_by_id = {source.id: source for source in request.source_events}
        ordered_items = tuple(
            sorted(
                request.memory_items,
                key=lambda item: (item.event_time or item.created_at, item.created_at, item.id),
            )
        )
        items: list[GraphFactPreseedItemResult] = []
        with graphiti_model_cache_context(
            project_memory_space_id=ordered_items[0].project_memory_space_id
            if ordered_items
            else "",
            source_event_ids=tuple(
                source_id
                for memory_item in ordered_items
                for source_id in memory_item.source_event_ids
            ),
        ):
            for memory_item in ordered_items:
                try:
                    result = await _direct_preseed_memory_item(
                        driver=driver,
                        embedder=embedder,
                        memory_item=memory_item,
                        source_events=tuple(
                            source_by_id[source_id]
                            for source_id in memory_item.source_event_ids
                            if source_id in source_by_id
                        ),
                    )
                except Exception as exc:
                    items.append(
                        GraphFactPreseedItemResult(
                            memory_id=memory_item.id,
                            result=None,
                            error_type=exc.__class__.__name__,
                            error_message=None,
                            reason_code="graph_direct_preseed_failed",
                            retryable=False,
                        )
                    )
                    continue
                items.append(
                    GraphFactPreseedItemResult(
                        memory_id=memory_item.id,
                        result=result,
                        error_type=None,
                        error_message=None,
                        reason_code=None,
                        retryable=False,
                    )
                )
        return GraphFactPreseedResult(items=tuple(items))

    async def _ingest_graph_jobs_bulk(
        self,
        request: GraphWriteBatchRequest,
        *,
        bulk_ingest: object,
    ) -> GraphWriteBatchResult:
        ordered_requests = tuple(sorted(request.requests, key=_graph_write_request_order))
        if not ordered_requests:
            return GraphWriteBatchResult(items=())
        for graph_request in ordered_requests:
            if not graph_request.source_events:
                raise ValueError("GraphitiAdapter requires at least one source event")

        try:
            raw_episodes = [_raw_episode(graph_request) for graph_request in ordered_requests]
            bulk_started = perf_counter()
            logger.info(
                "graphiti_adapter.semantic_bulk_started job_count=%s project_memory_space_id=%s",
                len(ordered_requests),
                ordered_requests[0].job.project_memory_space_id,
            )
            with graphiti_model_cache_context(
                project_memory_space_id=ordered_requests[0].job.project_memory_space_id,
                source_event_ids=tuple(
                    source_event_id
                    for graph_request in ordered_requests
                    for source_event_id in graph_request.job.source_event_ids
                ),
            ):
                results = await bulk_ingest(
                    raw_episodes,
                    group_id=_graphiti_group_id(ordered_requests[0].job.project_memory_space_id),
                )
        except Exception as exc:
            logger.info(
                "graphiti_adapter.semantic_bulk_failed job_count=%s error_type=%s",
                len(ordered_requests),
                exc.__class__.__name__,
            )
            return _blocked_batch_results(
                ordered_requests,
                error_type=exc.__class__.__name__,
                first_reason="graphiti_ordered_episode_failed",
                blocked_reason="graphiti_ordered_episode_blocked",
            )
        logger.info(
            "graphiti_adapter.semantic_bulk_completed job_count=%s result_count=%s duration_ms=%.1f",
            len(ordered_requests),
            len(results),
            _elapsed_ms(bulk_started),
        )

        if len(results) != len(ordered_requests):
            return _blocked_batch_results(
                ordered_requests,
                error_type="GraphitiBulkResultCountMismatch",
                first_reason="graphiti_ordered_episode_failed",
                blocked_reason="graphiti_ordered_episode_blocked",
            )

        items: list[GraphWriteBatchItemResult] = []
        for graph_request, result in zip(ordered_requests, results, strict=True):
            graph_result = _graph_write_result_from_graphiti_result(
                result,
                source_event_ids=graph_request.memory_item.source_event_ids,
            )
            items.append(
                GraphWriteBatchItemResult(
                    job_id=graph_request.job.id,
                    result=graph_result,
                    error_type=None,
                    error_message=None,
                    reason_code=None,
                    retryable=False,
                )
            )
        return GraphWriteBatchResult(items=tuple(items))

    async def _ingest_one(
        self,
        request: GraphWriteRequest,
        *,
        previous_episode_uuid: str | None,
    ) -> GraphWriteResult:
        if not request.source_events:
            raise ValueError("GraphitiAdapter requires at least one source event")

        reference_time = (
            request.memory_item.event_time
            or request.source_events[0].event_time
            or request.memory_item.created_at
        )
        with graphiti_model_cache_context(
            project_memory_space_id=request.job.project_memory_space_id,
            source_event_ids=request.job.source_event_ids,
        ):
            add_episode_started = perf_counter()
            logger.info(
                "graphiti_adapter.add_episode_call_started job_id=%s memory_id=%s title=%r "
                "source_event_count=%s previous_episode=%s",
                request.job.id,
                request.memory_item.id,
                request.memory_item.title,
                len(request.job.source_event_ids),
                bool(previous_episode_uuid),
            )
            result = await self._graphiti.add_episode(
                name=request.memory_item.title,
                episode_body=request.memory_item.content,
                source_description="MemWing graph write job",
                reference_time=reference_time,
                group_id=_graphiti_group_id(request.job.project_memory_space_id),
                uuid=_stable_graphiti_episode_uuid(request),
                previous_episode_uuids=[previous_episode_uuid] if previous_episode_uuid else None,
            )
            logger.info(
                "graphiti_adapter.add_episode_call_completed job_id=%s memory_id=%s duration_ms=%.1f",
                request.job.id,
                request.memory_item.id,
                _elapsed_ms(add_episode_started),
            )
        return _graph_write_result_from_graphiti_result(
            result,
            source_event_ids=request.memory_item.source_event_ids,
        )

    def cache_metrics_snapshot(self) -> dict[str, int]:
        snapshot: dict[str, int] = {}
        for source in self._cache_metrics_sources:
            _merge_metrics_snapshot(snapshot, source)
        return snapshot

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        raise NotImplementedError("Graphiti source redaction marker sync is not implemented")

    async def _search(
        self,
        query: MemorySearchQuery,
        *,
        trace_suffix: str,
    ) -> MemorySearchResult:
        edges = await self._graphiti.search(
            query.query,
            group_ids=[_graphiti_group_id(query.scope.project_memory_space_id)],
            num_results=query.limit,
        )
        items = tuple(_edge_to_result_item(edge) for edge in edges)
        return MemorySearchResult(
            contexts=tuple(item.text for item in items),
            results=items,
            next_cursor=None,
            trace_id=f"graphiti:{trace_suffix}",
        )


def _merge_metrics_snapshot(snapshot: dict[str, int], source: object) -> None:
    metrics = getattr(source, "cache_metrics", None)
    if metrics is None:
        metrics = getattr(source, "metrics", None)
    if metrics is None:
        return
    prefix = _metrics_prefix(source)
    for name in ("hits", "misses", "puts", "invalidations", "bypasses", "provider_calls"):
        value = getattr(metrics, name, None)
        if isinstance(value, int):
            snapshot[f"{prefix}_{name}"] = snapshot.get(f"{prefix}_{name}", 0) + value


def _metrics_prefix(source: object) -> str:
    name = source.__class__.__name__
    if "Embed" in name:
        return "embedding"
    if "LLM" in name:
        return "llm"
    return "model_cache"


def _load_graphiti_factory() -> GraphitiFactory:
    vendored_parent = Path(__file__).resolve().parent
    if str(vendored_parent) not in sys.path:
        sys.path.insert(0, str(vendored_parent))
    from graphiti_core import Graphiti

    return Graphiti
