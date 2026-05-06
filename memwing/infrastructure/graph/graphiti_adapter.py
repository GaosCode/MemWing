from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
import logging
from pathlib import Path
import re
import sys
from time import perf_counter
import uuid
from typing import Protocol

from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult, MemorySearchResultItem
from memwing.core.models import GraphFact, GraphWriteResult
from memwing.core.scope import EffectiveScope
from memwing.infrastructure.graph.graphiti_cache_context import graphiti_model_cache_context
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


def _edge_to_result_item(edge: object) -> MemorySearchResultItem:
    edge_id = _required_text_attr(edge, "uuid")
    fact = _required_text_attr(edge, "fact")
    return MemorySearchResultItem(
        id=edge_id,
        text=fact,
        score=_optional_float_attr(edge, "score"),
        source="graph_backend",
        source_event_ids=tuple(),
        memory_item_ids=tuple(),
        valid_from=_optional_datetime_attr(edge, "valid_at"),
        valid_to=_optional_datetime_attr(edge, "invalid_at"),
        metadata={"backend": "graphiti", "backend_object_type": "entity_edge"},
    )


def _edge_to_fact(edge: object, source_event_ids: tuple[str, ...]) -> GraphFact:
    edge_id = _required_text_attr(edge, "uuid")
    return GraphFact(
        backend="graphiti",
        fact_id=edge_id,
        fact_text=_required_text_attr(edge, "fact"),
        source_event_ids=source_event_ids,
        valid_from=_optional_datetime_attr(edge, "valid_at"),
        valid_to=_optional_datetime_attr(edge, "invalid_at"),
        invalidated_at=_optional_datetime_attr(edge, "expired_at"),
        confidence=_edge_confidence(edge),
        metadata={"backend_object_type": "entity_edge"},
    )


async def _direct_preseed_memory_item(
    *,
    driver: object,
    embedder: object,
    memory_item: object,
    source_events: tuple[object, ...],
) -> GraphWriteResult:
    vendored_parent = Path(__file__).resolve().parent
    if str(vendored_parent) not in sys.path:
        sys.path.insert(0, str(vendored_parent))
    from graphiti_core.edges import EntityEdge
    from graphiti_core.nodes import EntityNode, EpisodeType, EpisodicNode

    group_id = _graphiti_group_id(memory_item.project_memory_space_id)
    reference_time = (
        memory_item.valid_from
        or memory_item.event_time
        or (source_events[0].event_time if source_events else None)
        or memory_item.created_at
    )
    episode_uuid = _stable_direct_episode_uuid(memory_item)
    fact_uuid = _stable_direct_fact_uuid(memory_item)
    source_node = EntityNode(
        uuid=_stable_direct_entity_uuid(memory_item, "source"),
        name="MemWing benchmark expected memory",
        group_id=group_id,
        labels=["BenchmarkExpected"],
        created_at=memory_item.created_at,
        summary="Benchmark expected memory preseed source.",
        attributes={"preseed_mode": "direct_neo4j"},
    )
    target_node = EntityNode(
        uuid=_stable_direct_entity_uuid(memory_item, "target"),
        name=memory_item.title,
        group_id=group_id,
        labels=["BenchmarkMemoryItem"],
        created_at=memory_item.created_at,
        summary=memory_item.content,
        attributes={
            "preseed_mode": "direct_neo4j",
            "memory_item_id": memory_item.id,
        },
    )
    source_node.name_embedding, target_node.name_embedding, fact_embedding = (
        await _create_graphiti_embeddings(
            embedder,
            (
                source_node.name,
                target_node.name,
                memory_item.content,
            ),
        )
    )
    edge = EntityEdge(
        uuid=fact_uuid,
        group_id=group_id,
        source_node_uuid=source_node.uuid,
        target_node_uuid=target_node.uuid,
        created_at=memory_item.created_at,
        name="HAS_EXPECTED_FACT",
        fact=memory_item.content,
        fact_embedding=fact_embedding,
        episodes=[episode_uuid],
        expired_at=None,
        valid_at=memory_item.valid_from or memory_item.event_time,
        invalid_at=memory_item.valid_to,
        reference_time=reference_time,
        attributes={
            "confidence": 1.0,
            "preseed_mode": "direct_neo4j",
            "memory_item_id": memory_item.id,
            "source_event_ids": list(memory_item.source_event_ids),
        },
    )
    episode = EpisodicNode(
        uuid=episode_uuid,
        name=memory_item.title,
        group_id=group_id,
        source=EpisodeType.message,
        source_description="MemWing benchmark expected memory direct preseed",
        content=memory_item.content,
        valid_at=reference_time,
        entity_edges=[fact_uuid],
        created_at=memory_item.created_at,
        episode_metadata={
            "preseed_mode": "direct_neo4j",
            "memory_item_id": memory_item.id,
            "source_event_ids": list(memory_item.source_event_ids),
        },
    )
    await source_node.save(driver)
    await target_node.save(driver)
    await edge.save(driver)
    await episode.save(driver)
    graph_fact = GraphFact(
        backend="graphiti",
        fact_id=fact_uuid,
        fact_text=memory_item.content,
        source_event_ids=memory_item.source_event_ids,
        valid_from=edge.valid_at,
        valid_to=edge.invalid_at,
        invalidated_at=edge.expired_at,
        confidence=1.0,
        metadata={
            "backend_object_type": "entity_edge",
            "preseed_mode": "direct_neo4j",
        },
    )
    return GraphWriteResult(
        backend="graphiti",
        facts=(graph_fact,),
        invalidated_facts=(),
        backend_episode_refs=(episode_uuid,),
        backend_fact_refs=(fact_uuid,),
    )


async def _create_graphiti_embeddings(
    embedder: object,
    texts: tuple[str, ...],
) -> tuple[list[float], ...]:
    create_batch = getattr(embedder, "create_batch", None)
    if create_batch is not None:
        return tuple(await create_batch(list(texts)))
    create = getattr(embedder, "create")
    return tuple([float(value) for value in await create(text)] for text in texts)


def _graph_write_result_from_graphiti_result(
    result: object,
    *,
    source_event_ids: tuple[str, ...],
) -> GraphWriteResult:
    episode_refs = _episode_refs(result)
    edges = _edges(result)
    facts = tuple(_edge_to_fact(edge, source_event_ids) for edge in edges)
    return GraphWriteResult(
        backend="graphiti",
        facts=facts,
        invalidated_facts=tuple(fact for fact in facts if fact.invalidated_at is not None),
        backend_episode_refs=episode_refs,
        backend_fact_refs=tuple(fact.fact_id for fact in facts),
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


def _blocked_batch_results(
    requests: tuple[GraphWriteRequest, ...],
    *,
    error_type: str,
    first_reason: str,
    blocked_reason: str,
) -> GraphWriteBatchResult:
    items: list[GraphWriteBatchItemResult] = []
    for index, request in enumerate(requests):
        items.append(
            GraphWriteBatchItemResult(
                job_id=request.job.id,
                result=None,
                error_type=error_type if index == 0 else "GraphitiOrderedBatchBlocked",
                error_message=None,
                reason_code=first_reason if index == 0 else blocked_reason,
                retryable=True,
            )
        )
    return GraphWriteBatchResult(items=tuple(items))


def _safe_error_message(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    if len(text) > 500:
        return f"{text[:500]}...[truncated]"
    return text


def _episode_refs(result: object) -> tuple[str, ...]:
    episode = getattr(result, "episode", None)
    if episode is None:
        return tuple()
    uuid = getattr(episode, "uuid", None)
    if isinstance(uuid, str) and uuid.strip():
        return (uuid,)
    return tuple()


def _edges(result: object) -> tuple[object, ...]:
    edges = getattr(result, "edges", None)
    if edges is None:
        return tuple()
    return tuple(edges)


def _graph_write_request_order(request: GraphWriteRequest) -> tuple[datetime, datetime, str]:
    return (
        request.memory_item.event_time or request.source_events[0].event_time,
        request.job.created_at,
        request.job.id,
    )


def _stable_graphiti_episode_uuid(request: GraphWriteRequest) -> str:
    key = "|".join(
        (
            "graphiti",
            request.job.project_memory_space_id,
            request.memory_item.id,
            str(request.memory_item.lifecycle_revision),
            ",".join(request.job.source_event_ids),
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _stable_direct_episode_uuid(memory_item: object) -> str:
    return _stable_direct_uuid("graphiti_direct_episode", memory_item)


def _stable_direct_fact_uuid(memory_item: object) -> str:
    return _stable_direct_uuid("graphiti_direct_fact", memory_item)


def _stable_direct_entity_uuid(memory_item: object, role: str) -> str:
    return _stable_direct_uuid(f"graphiti_direct_entity:{role}", memory_item)


def _stable_direct_uuid(namespace: str, memory_item: object) -> str:
    key = "|".join(
        (
            namespace,
            memory_item.project_memory_space_id,
            memory_item.id,
            str(memory_item.lifecycle_revision),
            ",".join(memory_item.source_event_ids),
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _raw_episode(request: GraphWriteRequest) -> object:
    vendored_parent = Path(__file__).resolve().parent
    if str(vendored_parent) not in sys.path:
        sys.path.insert(0, str(vendored_parent))
    from graphiti_core.nodes import EpisodeType
    from graphiti_core.utils.bulk_utils import RawEpisode

    return RawEpisode(
        name=request.memory_item.title,
        uuid=_stable_graphiti_episode_uuid(request),
        content=request.memory_item.content,
        source_description="MemWing graph write job",
        source=EpisodeType.message,
        reference_time=(
            request.memory_item.event_time
            or request.source_events[0].event_time
            or request.memory_item.created_at
        ),
    )


def _edge_confidence(edge: object) -> float | None:
    attributes = getattr(edge, "attributes", None)
    if isinstance(attributes, dict):
        value = attributes.get("confidence")
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


def _required_text_attr(value: object, attr: str) -> str:
    text = getattr(value, attr, None)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Graphiti edge requires non-empty {attr}")
    return text


def _optional_float_attr(value: object, attr: str) -> float | None:
    raw = getattr(value, attr, None)
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return float(raw)
    return None


def _optional_datetime_attr(value: object, attr: str) -> datetime | None:
    raw = getattr(value, attr, None)
    if isinstance(raw, datetime):
        return raw
    return None


def _graphiti_group_id(project_memory_space_id: str) -> str:
    if re.fullmatch(r"[a-zA-Z0-9_-]+", project_memory_space_id):
        return project_memory_space_id
    readable = re.sub(r"[^a-zA-Z0-9_-]+", "_", project_memory_space_id).strip("_")
    if not readable:
        readable = "project"
    digest = sha1(project_memory_space_id.encode("utf-8")).hexdigest()[:12]
    return f"mw_{readable[:80]}_{digest}"


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def _load_graphiti_factory() -> GraphitiFactory:
    vendored_parent = Path(__file__).resolve().parent
    if str(vendored_parent) not in sys.path:
        sys.path.insert(0, str(vendored_parent))
    from graphiti_core import Graphiti

    return Graphiti
