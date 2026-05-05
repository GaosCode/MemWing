from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from memwing.ports.model_runtime import ModelCacheContext


@dataclass(frozen=True, slots=True)
class GraphitiModelCacheScope:
    project_memory_space_id: str
    source_event_ids: tuple[str, ...]


_CURRENT_SCOPE: ContextVar[GraphitiModelCacheScope | None] = ContextVar(
    "memwing_graphiti_model_cache_scope",
    default=None,
)


@contextmanager
def graphiti_model_cache_context(
    *,
    project_memory_space_id: str,
    source_event_ids: tuple[str, ...],
) -> Iterator[None]:
    token = _CURRENT_SCOPE.set(
        GraphitiModelCacheScope(
            project_memory_space_id=project_memory_space_id,
            source_event_ids=source_event_ids,
        )
    )
    try:
        yield
    finally:
        _CURRENT_SCOPE.reset(token)


def graphiti_embedding_cache_context() -> ModelCacheContext | None:
    scope = _CURRENT_SCOPE.get()
    if scope is None:
        return None
    return ModelCacheContext(
        project_memory_space_id=scope.project_memory_space_id,
        source_event_ids=scope.source_event_ids,
        role="graphiti_embedding",
        prompt_hash="none",
        schema_hash="graphiti_embedding:v1",
        cache_policy="required",
    )


def graphiti_extraction_cache_scope() -> GraphitiModelCacheScope | None:
    return _CURRENT_SCOPE.get()
