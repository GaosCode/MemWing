from __future__ import annotations

from datetime import datetime

from memwing.core.memory_search import MemorySearchResultItem
from memwing.core.models import GraphFact, GraphWriteResult

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
