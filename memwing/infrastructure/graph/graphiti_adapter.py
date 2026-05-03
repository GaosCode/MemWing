from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from pathlib import Path
import re
import sys
from typing import Protocol

from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult, MemorySearchResultItem
from memwing.core.models import GraphFact, GraphWriteResult
from memwing.core.scope import EffectiveScope
from memwing.ports.graph_backend import GraphWriteRequest


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


class GraphitiAdapter:
    def __init__(self, graphiti: GraphitiRuntime) -> None:
        self._graphiti = graphiti

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
        return cls(graphiti)

    async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
        return await self._search(query, trace_suffix="current")

    async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
        return await self._search(query, trace_suffix="history")

    async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
        if not request.source_events:
            raise ValueError("GraphitiAdapter requires at least one source event")

        reference_time = (
            request.memory_item.event_time
            or request.source_events[0].event_time
            or request.memory_item.created_at
        )
        result = await self._graphiti.add_episode(
            name=request.memory_item.title,
            episode_body=request.memory_item.content,
            source_description="MemWing graph write job",
            reference_time=reference_time,
            group_id=_graphiti_group_id(request.job.project_memory_space_id),
        )
        episode_refs = _episode_refs(result)
        edges = _edges(result)
        facts = tuple(_edge_to_fact(edge, request.memory_item.source_event_ids) for edge in edges)
        return GraphWriteResult(
            backend="graphiti",
            facts=facts,
            invalidated_facts=tuple(fact for fact in facts if fact.invalidated_at is not None),
            backend_episode_refs=episode_refs,
            backend_fact_refs=tuple(fact.fact_id for fact in facts),
        )

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


def _load_graphiti_factory() -> GraphitiFactory:
    vendored_parent = Path(__file__).resolve().parent
    if str(vendored_parent) not in sys.path:
        sys.path.insert(0, str(vendored_parent))
    from graphiti_core import Graphiti

    return Graphiti
