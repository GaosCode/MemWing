from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from memwing.api.runtime_config import (
    database_url_from_env,
    evidence_backend_from_env,
    evidence_vector_size_from_env,
    graph_backend_from_env,
    graphiti_neo4j_password_from_env,
    graphiti_neo4j_uri_from_env,
    graphiti_neo4j_user_from_env,
    qdrant_api_key_from_env,
    qdrant_collection_from_env,
    qdrant_url_from_env,
)
from memwing.application.access_service import MemoryAccessService
from memwing.application.gateway_service import MemoryGateway
from memwing.application.scope_resolver import ScopeResolver
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter
from memwing.infrastructure.db.postgres import PostgresDataStore
from memwing.infrastructure.db.postgres_connection import PooledPostgresConnection
from memwing.infrastructure.evidence.qdrant_index import QdrantEvidenceConfig, QdrantEvidenceIndex
from memwing.infrastructure.graph.graphiti_adapter import GraphitiAdapter, GraphitiConnectionConfig
from memwing.infrastructure.graph.graphiti_embedder import GraphitiMemWingEmbedder
from memwing.infrastructure.graph.graphiti_llm import GraphitiMemWingLLMClient
from memwing.infrastructure.graph.graphiti_reranker import GraphitiNoProviderReranker
from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawRuntimeEmbeddingClient,
    OpenClawRuntimeLLMClient,
)
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort
from memwing.ports.model_runtime import EmbeddingModelClient, LLMModelClient, MemWingModelRole


@dataclass(frozen=True, slots=True)
class OpenClawRuntimeHandle:
    runtime: OpenClawAdapter
    connection: PooledPostgresConnection
    graph_backend: GraphBackendPort | None = None
    evidence_index: EvidenceIndexPort | None = None

    async def close(self) -> None:
        await _close_optional(self.evidence_index)
        await _close_optional(self.graph_backend)
        await self.connection.close()


def create_openclaw_adapter_from_store(
    store: EventStoreUnitOfWorkPort,
    *,
    graph_backend: GraphBackendPort | None = None,
    evidence_index: EvidenceIndexPort | None = None,
) -> OpenClawAdapter:
    scope_resolver = ScopeResolver(store)
    return OpenClawAdapter(
        MemoryGateway(store, scope_resolver),
        MemoryAccessService(
            scope_resolver,
            store,
            graph_backend=graph_backend,
            evidence_index=evidence_index,
        ),
    )


async def create_openclaw_adapter_from_postgres(
    database_url: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
    graph_backend: GraphBackendPort | None = None,
    evidence_index: EvidenceIndexPort | None = None,
) -> OpenClawRuntimeHandle:
    connection = await PooledPostgresConnection.connect(
        database_url,
        min_size=min_size,
        max_size=max_size,
    )
    try:
        runtime = create_openclaw_adapter_from_store(
            PostgresDataStore(connection),
            graph_backend=graph_backend,
            evidence_index=evidence_index,
        )
    except Exception:
        await connection.close()
        raise
    return OpenClawRuntimeHandle(
        runtime=runtime,
        connection=connection,
        graph_backend=graph_backend,
        evidence_index=evidence_index,
    )


async def create_openclaw_adapter_from_env(
    env: Mapping[str, str] | None = None,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> OpenClawRuntimeHandle:
    graph_backend = _graph_backend_from_env(env)
    evidence_index = _evidence_index_from_env(env)
    return await create_openclaw_adapter_from_postgres(
        database_url_from_env(env),
        min_size=min_size,
        max_size=max_size,
        graph_backend=graph_backend,
        evidence_index=evidence_index,
    )


def _graph_backend_from_env(env: Mapping[str, str] | None) -> GraphBackendPort | None:
    if graph_backend_from_env(env) == "disabled":
        return None
    resolver = MemWingModelConfigResolver.from_env(env)
    llm_client = _llm_client_for_role(resolver, "graphiti_extraction")
    embedding_client = _embedding_client_for_role(resolver, "graphiti_embedding")
    return GraphitiAdapter.from_clients(
        GraphitiConnectionConfig(
            uri=graphiti_neo4j_uri_from_env(env),
            user=graphiti_neo4j_user_from_env(env),
            password=graphiti_neo4j_password_from_env(env),
        ),
        llm_client=GraphitiMemWingLLMClient(llm_client),
        embedder=GraphitiMemWingEmbedder(embedding_client),
        cross_encoder=GraphitiNoProviderReranker(),
    )


def _evidence_index_from_env(env: Mapping[str, str] | None) -> EvidenceIndexPort | None:
    if evidence_backend_from_env(env) == "disabled":
        return None
    resolver = MemWingModelConfigResolver.from_env(env)
    embedding_client = _embedding_client_for_role(resolver, "evidence_embedding")
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
        return OpenClawRuntimeLLMClient.from_model_selection(selection)
    raise ValueError(f"{role} requires openclaw model runtime")


def _embedding_client_for_role(
    resolver: MemWingModelConfigResolver,
    role: MemWingModelRole,
) -> EmbeddingModelClient:
    selection = resolver.selection_for(role)
    if selection.runtime == "openclaw":
        return OpenClawRuntimeEmbeddingClient.from_model_selection(selection)
    raise ValueError(f"{role} requires openclaw embedding runtime")


async def _close_optional(value: object) -> None:
    close = getattr(value, "close", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result


__all__ = (
    "OpenClawRuntimeHandle",
    "create_openclaw_adapter_from_env",
    "create_openclaw_adapter_from_postgres",
    "create_openclaw_adapter_from_store",
)
