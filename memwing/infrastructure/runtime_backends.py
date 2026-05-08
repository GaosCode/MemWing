from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from memwing.api.runtime_config import (
    evidence_backend_from_env,
    evidence_vector_size_from_env,
    graph_backend_from_env,
    graphiti_neo4j_password_from_env,
    graphiti_neo4j_uri_from_env,
    graphiti_neo4j_user_from_env,
    graphiti_semantic_bulk_enabled_from_env,
    qdrant_api_key_from_env,
    qdrant_collection_from_env,
    qdrant_url_from_env,
)
from memwing.infrastructure.evidence.qdrant_index import QdrantEvidenceConfig, QdrantEvidenceIndex
from memwing.infrastructure.graph.graphiti_adapter import GraphitiAdapter, GraphitiConnectionConfig
from memwing.infrastructure.graph.graphiti_embedder import GraphitiMemWingEmbedder
from memwing.infrastructure.graph.graphiti_llm import GraphitiMemWingLLMClient
from memwing.infrastructure.graph.graphiti_reranker import GraphitiNoProviderReranker
from memwing.infrastructure.llm.caching_embedding import CachingEmbeddingModelClient
from memwing.infrastructure.llm.long_term_filter import MemWingLongTermFilterAdapter
from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawRuntimeConfig,
    OpenClawRuntimeEmbeddingClient,
    OpenClawRuntimeLLMClient,
)
from memwing.infrastructure.llm.page_memory_synthesis import MemWingPageMemorySynthesisAdapter
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort
from memwing.ports.model_runtime import EmbeddingModelClient, LLMModelClient, MemWingModelRole


@dataclass(frozen=True, slots=True)
class RuntimeBackendsHandle:
    graph_backend: GraphBackendPort | None
    evidence_index: EvidenceIndexPort | None
    long_term_filter: MemWingLongTermFilterAdapter | None = None
    page_memory_synthesis: MemWingPageMemorySynthesisAdapter | None = None

    async def close(self) -> None:
        await close_optional(self.evidence_index)
        await close_optional(self.graph_backend)


def create_api_backends(env: Mapping[str, str] | None = None) -> RuntimeBackendsHandle:
    return RuntimeBackendsHandle(
        graph_backend=_graph_backend_from_env(env),
        evidence_index=_evidence_index_from_env(env),
    )


def create_pipeline_backends(
    env: Mapping[str, str] | None,
    store: EventStoreUnitOfWorkPort,
) -> RuntimeBackendsHandle:
    resolver = MemWingModelConfigResolver.from_env(env)
    return RuntimeBackendsHandle(
        graph_backend=_graph_backend_from_env(env, store=store, resolver=resolver),
        evidence_index=_evidence_index_from_env(env, store=store, resolver=resolver),
        long_term_filter=_long_term_filter_adapter(resolver, store),
        page_memory_synthesis=_page_memory_synthesis_adapter(resolver, store),
    )


def _graph_backend_from_env(
    env: Mapping[str, str] | None,
    *,
    store: EventStoreUnitOfWorkPort | None = None,
    resolver: MemWingModelConfigResolver | None = None,
) -> GraphBackendPort | None:
    if graph_backend_from_env(env) == "disabled":
        return None
    resolver = resolver or MemWingModelConfigResolver.from_env(env)
    llm_client = _llm_client_for_role(resolver, "graphiti_extraction")
    embedding_client = _embedding_client_for_role(resolver, "graphiti_embedding")
    graphiti_selection = resolver.selection_for("graphiti_extraction")
    graphiti_llm_cache_kwargs = (
        {
            "cache_unit_of_work": store,
            "cache_runtime": graphiti_selection.runtime,
            "cache_model": graphiti_selection.model or "openclaw",
            "cache_transport": graphiti_selection.transport or "local",
        }
        if store is not None
        else {}
    )
    if store is not None:
        embedding_client = _caching_embedding_client_for_role(
            store,
            resolver,
            "graphiti_embedding",
            embedding_client,
        )
    return GraphitiAdapter.from_clients(
        GraphitiConnectionConfig(
            uri=graphiti_neo4j_uri_from_env(env),
            user=graphiti_neo4j_user_from_env(env),
            password=graphiti_neo4j_password_from_env(env),
            semantic_bulk_ingest_enabled=graphiti_semantic_bulk_enabled_from_env(env),
        ),
        llm_client=GraphitiMemWingLLMClient(
            llm_client,
            **graphiti_llm_cache_kwargs,
        ),
        embedder=GraphitiMemWingEmbedder(embedding_client),
        cross_encoder=GraphitiNoProviderReranker(),
    )


def _evidence_index_from_env(
    env: Mapping[str, str] | None,
    *,
    store: EventStoreUnitOfWorkPort | None = None,
    resolver: MemWingModelConfigResolver | None = None,
) -> EvidenceIndexPort | None:
    if evidence_backend_from_env(env) == "disabled":
        return None
    resolver = resolver or MemWingModelConfigResolver.from_env(env)
    embedding_client = _embedding_client_for_role(resolver, "evidence_embedding")
    if store is not None:
        embedding_client = _caching_embedding_client_for_role(
            store,
            resolver,
            "evidence_embedding",
            embedding_client,
        )
    return QdrantEvidenceIndex.from_config(
        QdrantEvidenceConfig(
            url=qdrant_url_from_env(env),
            api_key=qdrant_api_key_from_env(env),
            collection=qdrant_collection_from_env(env),
            vector_size=evidence_vector_size_from_env(env),
        ),
        embedding_client=embedding_client,
    )


def _llm_client_for_role(
    resolver: MemWingModelConfigResolver,
    role: MemWingModelRole,
) -> LLMModelClient:
    selection = resolver.selection_for(role)
    if selection.runtime == "openclaw":
        return OpenClawRuntimeLLMClient(OpenClawRuntimeConfig.from_env_model_selection(selection))
    raise ValueError(f"{role} requires openclaw model runtime")


def _embedding_client_for_role(
    resolver: MemWingModelConfigResolver,
    role: MemWingModelRole,
) -> EmbeddingModelClient:
    selection = resolver.selection_for(role)
    if selection.runtime == "openclaw":
        return OpenClawRuntimeEmbeddingClient(OpenClawRuntimeConfig.from_env_model_selection(selection))
    raise ValueError(f"{role} requires openclaw embedding runtime")


def _long_term_filter_adapter(
    resolver: MemWingModelConfigResolver,
    store: EventStoreUnitOfWorkPort,
) -> MemWingLongTermFilterAdapter:
    selection = resolver.selection_for("long_term_filter")
    return MemWingLongTermFilterAdapter(
        _llm_client_for_role(resolver, "long_term_filter"),
        cache_unit_of_work=store,
        cache_runtime=selection.runtime,
        cache_model=selection.model or "openclaw",
        cache_transport=selection.transport or "local",
    )


def _page_memory_synthesis_adapter(
    resolver: MemWingModelConfigResolver,
    store: EventStoreUnitOfWorkPort,
) -> MemWingPageMemorySynthesisAdapter:
    selection = resolver.selection_for("page_memory")
    return MemWingPageMemorySynthesisAdapter(
        _llm_client_for_role(resolver, "page_memory"),
        cache_unit_of_work=store,
        cache_runtime=selection.runtime,
        cache_model=selection.model or "openclaw",
        cache_transport=selection.transport or "local",
    )


def _caching_embedding_client_for_role(
    store: EventStoreUnitOfWorkPort,
    resolver: MemWingModelConfigResolver,
    role: MemWingModelRole,
    provider: EmbeddingModelClient,
) -> EmbeddingModelClient:
    selection = resolver.selection_for(role)
    return CachingEmbeddingModelClient(
        store,
        provider,
        runtime=selection.runtime,
        model=selection.model or "openclaw",
        transport=selection.transport or "local",
    )


async def close_optional(value: object) -> None:
    close = getattr(value, "close", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result


__all__ = (
    "RuntimeBackendsHandle",
    "close_optional",
    "create_api_backends",
    "create_pipeline_backends",
)
