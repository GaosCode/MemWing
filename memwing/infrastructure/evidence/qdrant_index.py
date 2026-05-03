from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult, MemorySearchResultItem
from memwing.core.models import SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.ports.model_runtime import EmbeddingModelClient


class QdrantEvidenceClient(Protocol):
    async def collection_exists(self, collection_name: str) -> bool:
        ...

    async def create_collection(
        self,
        *,
        collection_name: str,
        vectors_config: models.VectorParams,
    ) -> object:
        ...

    async def upsert(
        self,
        *,
        collection_name: str,
        points: list[models.PointStruct],
        wait: bool = True,
    ) -> object:
        ...

    async def query_points(
        self,
        *,
        collection_name: str,
        query: list[float],
        query_filter: models.Filter,
        limit: int,
        with_payload: bool = True,
    ) -> object:
        ...

    async def set_payload(
        self,
        *,
        collection_name: str,
        payload: dict[str, object],
        points: models.Filter,
        wait: bool = True,
    ) -> object:
        ...

    async def close(self) -> None:
        ...


@dataclass(frozen=True, slots=True)
class QdrantEvidenceConfig:
    url: str
    collection: str
    vector_size: int
    api_key: str | None = None


class QdrantEvidenceIndex:
    def __init__(
        self,
        *,
        client: QdrantEvidenceClient,
        embedding_client: EmbeddingModelClient,
        collection: str,
        vector_size: int,
    ) -> None:
        if not collection.strip():
            raise ValueError("Qdrant evidence collection is required")
        if vector_size <= 0:
            raise ValueError("Qdrant evidence vector_size must be positive")
        self._client = client
        self._embedding_client = embedding_client
        self._collection = collection
        self._vector_size = vector_size
        self._collection_ready = False

    @classmethod
    def from_config(
        cls,
        config: QdrantEvidenceConfig,
        *,
        embedding_client: EmbeddingModelClient,
    ) -> QdrantEvidenceIndex:
        return cls(
            client=AsyncQdrantClient(url=config.url, api_key=config.api_key),
            embedding_client=embedding_client,
            collection=config.collection,
            vector_size=config.vector_size,
        )

    async def index_source_event(self, source_event: SourceEvent, scope: EffectiveScope) -> None:
        await self.index_source_events((source_event,), scope)

    async def index_source_events(
        self,
        source_events: tuple[SourceEvent, ...],
        scope: EffectiveScope,
    ) -> None:
        await self._ensure_collection()
        indexable = tuple(
            (source_event, source_event.content.strip())
            for source_event in source_events
            if source_event.content.strip()
        )
        if not indexable:
            return
        vectors = await self._embedding_client.embed_batch(tuple(text for _, text in indexable))
        if len(vectors) != len(indexable):
            raise ValueError("embedding batch result count does not match source event count")
        points: list[models.PointStruct] = []
        for (source_event, chunk_text), vector in zip(indexable, vectors, strict=True):
            _validate_vector_size(vector, expected_size=self._vector_size)
            payload = _source_event_payload(
                source_event=source_event,
                scope=scope,
                chunk_text=chunk_text,
            )
            points.append(
                models.PointStruct(
                    id=_point_id(source_event.id, chunk_index=0),
                    vector=list(vector),
                    payload=payload,
                )
            )
        await self._client.upsert(
            collection_name=self._collection,
            points=points,
            wait=True,
        )

    async def search(self, query: MemorySearchQuery) -> MemorySearchResult:
        await self._ensure_collection()
        vector = await self._embedding_client.embed(query.query)
        _validate_vector_size(vector, expected_size=self._vector_size)
        response = await self._client.query_points(
            collection_name=self._collection,
            query=list(vector),
            query_filter=_scope_filter(query.scope),
            limit=query.limit,
            with_payload=True,
        )
        points = _response_points(response)
        items = tuple(_point_to_result_item(point) for point in points)
        return MemorySearchResult(
            contexts=tuple(item.text for item in items),
            results=items,
            next_cursor=None,
            trace_id=query.trace_id or "qdrant:evidence_index",
        )

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        await self._ensure_collection()
        await self._client.set_payload(
            collection_name=self._collection,
            payload={"redacted": True},
            points=_source_event_filter(source_event_id=source_event_id, scope=scope),
            wait=True,
        )

    async def close(self) -> None:
        await self._client.close()

    async def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        exists = await self._client.collection_exists(self._collection)
        if not exists:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(
                    size=self._vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
        self._collection_ready = True


def _source_event_payload(
    *,
    source_event: SourceEvent,
    scope: EffectiveScope,
    chunk_text: str,
) -> dict[str, object]:
    return {
        "source_event_id": source_event.id,
        "project_memory_space_id": scope.project_memory_space_id,
        "group_id": source_event.group_id,
        "thread_id": source_event.thread_id,
        "shared_group_id": source_event.shared_group_id,
        "source_kind": source_event.source_type,
        "redacted": source_event.purged_at is not None,
        "created_at": _datetime_text(source_event.created_at),
        "content_hash": sha256(chunk_text.encode("utf-8")).hexdigest(),
        "text": chunk_text,
        "chunk_index": 0,
    }


def _scope_filter(scope: EffectiveScope) -> models.Filter:
    conditions: list[models.Condition] = [
        _match_value("project_memory_space_id", scope.project_memory_space_id),
        _match_value("redacted", False),
    ]
    if scope.group_ids is not None:
        conditions.append(_match_group_ids(scope.group_ids))
    if scope.thread_id is not None:
        conditions.append(_match_value("thread_id", scope.thread_id))
    if scope.shared_group_id is not None:
        conditions.append(_match_value("shared_group_id", scope.shared_group_id))
    return models.Filter(must=conditions)


def _source_event_filter(*, source_event_id: str, scope: EffectiveScope) -> models.Filter:
    base_filter = _scope_filter(scope)
    return models.Filter(
        must=(
            *tuple(base_filter.must or ()),
            _match_value("source_event_id", source_event_id),
        )
    )


def _match_value(key: str, value: object) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _match_group_ids(group_ids: tuple[str, ...]) -> models.FieldCondition:
    if len(group_ids) == 1:
        return _match_value("group_id", group_ids[0])
    return models.FieldCondition(key="group_id", match=models.MatchAny(any=list(group_ids)))


def _response_points(response: object) -> tuple[object, ...]:
    points = getattr(response, "points", None)
    if points is None:
        return tuple(response) if isinstance(response, list | tuple) else tuple()
    return tuple(points)


def _point_to_result_item(point: object) -> MemorySearchResultItem:
    payload = getattr(point, "payload", None)
    if not isinstance(payload, dict):
        payload = {}
    source_event_id = _required_text(payload.get("source_event_id"), "source_event_id")
    text = _required_text(payload.get("text"), "text")
    return MemorySearchResultItem(
        id=str(getattr(point, "id", _point_id(source_event_id, chunk_index=0))),
        text=text,
        score=_optional_float(getattr(point, "score", None)),
        source="evidence_index",
        source_event_ids=(source_event_id,),
        memory_item_ids=(),
        valid_from=None,
        valid_to=None,
        metadata={
            "source_kind": payload.get("source_kind"),
            "content_hash": payload.get("content_hash"),
            "chunk_index": payload.get("chunk_index"),
        },
    )


def _point_id(source_event_id: str, *, chunk_index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"memwing:evidence:{source_event_id}:{chunk_index}"))


def _validate_vector_size(vector: tuple[float, ...], *, expected_size: int) -> None:
    if len(vector) != expected_size:
        raise ValueError("embedding vector size does not match Qdrant evidence configuration")


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Qdrant evidence payload requires {field_name}")
    return value


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


__all__ = ("QdrantEvidenceConfig", "QdrantEvidenceIndex")
