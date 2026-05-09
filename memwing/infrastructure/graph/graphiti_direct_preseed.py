from __future__ import annotations

from pathlib import Path
import sys
import uuid

from memwing.core.models import GraphFact, GraphWriteResult
from memwing.infrastructure.graph.graphiti_safety import _graphiti_group_id

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
