from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import os

from memwing.api.runtime_config import (
    auto_push_enabled_from_env,
    database_url_from_env,
    evidence_backend_from_env,
    evidence_vector_size_from_env,
    feishu_push_config_from_env,
    graph_backend_from_env,
    graph_write_batch_size_from_env,
    graph_write_max_global_concurrency_from_env,
    graph_write_max_project_concurrency_from_env,
    graph_write_timeout_seconds_from_env,
    graphiti_semantic_bulk_enabled_from_env,
    graphiti_neo4j_password_from_env,
    graphiti_neo4j_uri_from_env,
    graphiti_neo4j_user_from_env,
    qdrant_api_key_from_env,
    qdrant_collection_from_env,
    qdrant_url_from_env,
)
from memwing.application.access_service import MemoryAccessService
from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.application.gateway_service import MemoryGateway
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.application.long_term_filter_service import LongTermFilterService
from memwing.application.control_service import ControlService
from memwing.application.page_memory_service import PageMemoryService
from memwing.application.pipeline_readiness_service import PipelineReadinessService
from memwing.application.push_trigger_service import PushTriggerService
from memwing.application.scope_resolver import ScopeResolver
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter
from memwing.infrastructure.db.postgres import PostgresDataStore
from memwing.infrastructure.db.postgres_benchmark_admin import PostgresBenchmarkAdminStore
from memwing.infrastructure.db.postgres_connection import PooledPostgresConnection
from memwing.infrastructure.db.postgres_schema import ensure_postgres_schema_compatibility
from memwing.infrastructure.db.sqlite_store import SQLiteDataStore
from memwing.infrastructure.evidence.qdrant_index import QdrantEvidenceConfig, QdrantEvidenceIndex
from memwing.infrastructure.graph.graphiti_adapter import GraphitiAdapter, GraphitiConnectionConfig
from memwing.infrastructure.graph.graphiti_embedder import GraphitiMemWingEmbedder
from memwing.infrastructure.graph.graphiti_llm import GraphitiMemWingLLMClient
from memwing.infrastructure.graph.graphiti_reranker import GraphitiNoProviderReranker
from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver
from memwing.infrastructure.llm.caching_embedding import CachingEmbeddingModelClient
from memwing.infrastructure.llm.long_term_filter import MemWingLongTermFilterAdapter
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawRuntimeConfig,
    OpenClawRuntimeEmbeddingClient,
    OpenClawRuntimeLLMClient,
)
from memwing.infrastructure.llm.page_memory_synthesis import MemWingPageMemorySynthesisAdapter
from memwing.infrastructure.platforms.feishu_openapi import FeishuOpenApiPushSender
from memwing.infrastructure.platforms.feishu_push import FeishuPushDispatcher
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort
from memwing.ports.model_runtime import EmbeddingModelClient, LLMModelClient, MemWingModelRole
from memwing.ports.platform_connector import PlatformConnectorPort
from memwing.workers.benchmark_drain import BenchmarkDrainWorker
from memwing.workers.derived_outbox_worker import DerivedOutboxWorker
from memwing.workers.graph_write_worker import GraphWriteWorker
from memwing.workers.page_memory_worker import PageMemoryWorker
from memwing.workers.runner import MemWingWorkerRunner


@dataclass(frozen=True, slots=True)
class OpenClawRuntimeHandle:
    runtime: OpenClawAdapter
    connection: PooledPostgresConnection
    graph_backend: GraphBackendPort | None = None
    evidence_index: EvidenceIndexPort | None = None
    benchmark_admin: BenchmarkAdminService | None = None
    pipeline_readiness: PipelineReadinessService | None = None

    async def close(self) -> None:
        await _close_optional(self.evidence_index)
        await _close_optional(self.graph_backend)
        await self.connection.close()


@dataclass(frozen=True, slots=True)
class MemWingWorkerRuntimeHandle:
    runner: MemWingWorkerRunner
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
    auto_push_enabled: bool = False,
) -> OpenClawAdapter:
    scope_resolver = ScopeResolver(store)
    return OpenClawAdapter(
        MemoryGateway(
            store,
            scope_resolver,
            outbox_job_types=_gateway_outbox_job_types(auto_push_enabled=auto_push_enabled),
        ),
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
    benchmark_admin_enabled: bool = False,
    model_env: Mapping[str, str] | None = None,
) -> OpenClawRuntimeHandle:
    connection = await PooledPostgresConnection.connect(
        database_url,
        min_size=min_size,
        max_size=max_size,
    )
    try:
        await ensure_postgres_schema_compatibility(connection)
        store = PostgresDataStore(connection)
        runtime = create_openclaw_adapter_from_store(
            store,
            graph_backend=graph_backend,
            evidence_index=evidence_index,
            auto_push_enabled=auto_push_enabled_from_env(model_env),
        )
        benchmark_admin = (
            _benchmark_admin_service(
                store=store,
                connection=connection,
                graph_backend=graph_backend,
                evidence_index=evidence_index,
                env=model_env,
            )
            if benchmark_admin_enabled
            else None
        )
        pipeline_readiness = PipelineReadinessService(
            store,
            evidence_enabled=evidence_index is not None,
            graph_enabled=graph_backend is not None,
        )
    except Exception:
        await connection.close()
        raise
    return OpenClawRuntimeHandle(
        runtime=runtime,
        connection=connection,
        graph_backend=graph_backend,
        evidence_index=evidence_index,
        benchmark_admin=benchmark_admin,
        pipeline_readiness=pipeline_readiness,
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
        model_env=env,
    )


async def create_openclaw_adapter_with_benchmark_admin_from_env(
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
        benchmark_admin_enabled=True,
        model_env=env,
    )


async def create_worker_runner_from_env(
    env: Mapping[str, str] | None = None,
    *,
    min_size: int = 1,
    max_size: int = 10,
    worker_id: str = "memwing_worker",
) -> MemWingWorkerRuntimeHandle:
    if _storage_backend_from_env(env) == "sqlite":
        store = SQLiteDataStore.from_path(_lite_db_path_from_env(env))
        runner = _worker_runner_from_store(
            store,
            graph_backend=None,
            evidence_index=None,
            env=env,
            worker_id=worker_id,
        )
        return MemWingWorkerRuntimeHandle(
            runner=runner,
            connection=_NoopConnection(),
            graph_backend=None,
            evidence_index=None,
        )
    connection = await PooledPostgresConnection.connect(
        database_url_from_env(env),
        min_size=min_size,
        max_size=max_size,
    )
    try:
        await ensure_postgres_schema_compatibility(connection)
        store = PostgresDataStore(connection)
        graph_backend = _graph_backend_from_env(env, store=store)
        evidence_index = _evidence_index_from_env(env, store=store)
        runner = _worker_runner_from_store(
            store,
            graph_backend=graph_backend,
            evidence_index=evidence_index,
            env=env,
            worker_id=worker_id,
        )
    except Exception:
        await _close_optional(evidence_index)
        await _close_optional(graph_backend)
        await connection.close()
        raise
    return MemWingWorkerRuntimeHandle(
        runner=runner,
        connection=connection,
        graph_backend=graph_backend,
        evidence_index=evidence_index,
    )


def _worker_runner_from_store(
    store: EventStoreUnitOfWorkPort,
    *,
    graph_backend: GraphBackendPort | None,
    evidence_index: EvidenceIndexPort | None,
    env: Mapping[str, str] | None,
    worker_id: str,
) -> MemWingWorkerRunner:
    resolver = MemWingModelConfigResolver.from_env(env)
    scope_resolver = ScopeResolver(store)
    lifecycle_transition = LifecycleTransitionService(store)
    long_term_filter = LongTermFilterService(
        store,
        _long_term_filter_adapter(resolver, store),
        lifecycle_transition=lifecycle_transition,
    )
    page_memory_worker = PageMemoryWorker(
        store,
        PageMemoryService(
            store,
            _page_memory_synthesis_adapter(resolver, store),
        ),
        scope_resolver=scope_resolver,
    )
    graph_write_worker = (
        GraphWriteWorker(
            store,
            graph_backend=graph_backend,
            lifecycle_transition=lifecycle_transition,
            worker_id=f"{worker_id}:graph",
            backend_timeout=timedelta(seconds=graph_write_timeout_seconds_from_env(env)),
            batch_size=graph_write_batch_size_from_env(env),
            max_project_concurrency=graph_write_max_project_concurrency_from_env(env),
            max_global_concurrency=graph_write_max_global_concurrency_from_env(env),
        )
        if graph_backend is not None
        else None
    )
    derived_outbox_worker = DerivedOutboxWorker(
        store,
        evidence_index=evidence_index,
        long_term_filter=long_term_filter,
        page_memory_worker=page_memory_worker,
        worker_id=f"{worker_id}:outbox",
        control_service=ControlService(store, platform_connectors=_platform_connectors_from_env(env)),
        push_trigger_service=(
            PushTriggerService(store) if auto_push_enabled_from_env(env) else None
        ),
    )
    return MemWingWorkerRunner(
        derived_outbox_worker=derived_outbox_worker,
        graph_write_worker=graph_write_worker,
    )


def _graph_backend_from_env(
    env: Mapping[str, str] | None,
    *,
    store: EventStoreUnitOfWorkPort | None = None,
) -> GraphBackendPort | None:
    if graph_backend_from_env(env) == "disabled":
        return None
    resolver = MemWingModelConfigResolver.from_env(env)
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
) -> EvidenceIndexPort | None:
    if evidence_backend_from_env(env) == "disabled":
        return None
    resolver = MemWingModelConfigResolver.from_env(env)
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


def _platform_connectors_from_env(env: Mapping[str, str] | None) -> dict[str, PlatformConnectorPort]:
    feishu_config = feishu_push_config_from_env(env)
    if feishu_config is None:
        return {}
    return {
        "feishu": FeishuPushDispatcher(
            FeishuOpenApiPushSender(
                app_id=feishu_config.app_id,
                app_secret=feishu_config.app_secret,
                receive_id_type=feishu_config.receive_id_type,
                api_base_url=feishu_config.api_base_url,
                timeout_seconds=feishu_config.timeout_seconds,
            )
        )
    }


def _gateway_outbox_job_types(*, auto_push_enabled: bool) -> tuple[str, ...]:
    job_types = (
        "evidence.index_source_event",
        "working_memory.append",
        "page_memory.maybe_rebuild",
        "long_term_filter.classify",
    )
    if auto_push_enabled:
        return (*job_types, "push_candidate.trigger")
    return job_types


def _benchmark_admin_service(
    *,
    store: EventStoreUnitOfWorkPort,
    connection: PooledPostgresConnection,
    graph_backend: GraphBackendPort | None,
    evidence_index: EvidenceIndexPort | None,
    env: Mapping[str, str] | None,
) -> BenchmarkAdminService:
    resolver = MemWingModelConfigResolver.from_env(env)
    scope_resolver = ScopeResolver(store)
    lifecycle_transition = LifecycleTransitionService(store)
    long_term_filter = LongTermFilterService(
        store,
        _long_term_filter_adapter(resolver, store),
        lifecycle_transition=lifecycle_transition,
    )
    page_memory_worker = PageMemoryWorker(
        store,
        PageMemoryService(
            store,
            _page_memory_synthesis_adapter(resolver, store),
        ),
        scope_resolver=scope_resolver,
    )
    graph_write_worker = (
        GraphWriteWorker(
            store,
            graph_backend=graph_backend,
            lifecycle_transition=lifecycle_transition,
            worker_id="benchmark_graph_write",
            retry_delay=timedelta(0),
            backend_timeout=timedelta(seconds=graph_write_timeout_seconds_from_env(env)),
            batch_size=graph_write_batch_size_from_env(env),
            max_project_concurrency=graph_write_max_project_concurrency_from_env(env),
            max_global_concurrency=graph_write_max_global_concurrency_from_env(env),
        )
        if graph_backend is not None
        else None
    )
    drain_worker = BenchmarkDrainWorker(
        store,
        evidence_index=evidence_index,
        long_term_filter=long_term_filter,
        page_memory_worker=page_memory_worker,
        graph_write_worker=graph_write_worker,
    )
    return BenchmarkAdminService(
        unit_of_work=store,
        admin_store=PostgresBenchmarkAdminStore(connection),
        drain_worker=drain_worker,
        graph_backend=graph_backend,
        evidence_index=evidence_index,
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


async def _close_optional(value: object) -> None:
    close = getattr(value, "close", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result


def _storage_backend_from_env(env: Mapping[str, str] | None) -> str:
    source = os.environ if env is None else env
    return source.get("MEMWING_STORAGE_BACKEND", "").strip().casefold()


def _lite_db_path_from_env(env: Mapping[str, str] | None) -> str:
    source = os.environ if env is None else env
    return source.get("MEMWING_LITE_DB_PATH", "").strip() or "~/.memwing/memwing.db"


class _NoopConnection:
    async def close(self) -> None:
        return None


__all__ = (
    "MemWingWorkerRuntimeHandle",
    "OpenClawRuntimeHandle",
    "create_openclaw_adapter_from_env",
    "create_openclaw_adapter_with_benchmark_admin_from_env",
    "create_openclaw_adapter_from_postgres",
    "create_openclaw_adapter_from_store",
    "create_worker_runner_from_env",
)
