from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import os

from memwing.api.runtime_config import (
    auto_push_enabled_from_env,
    database_url_from_env,
    feishu_push_config_from_env,
    graph_write_batch_size_from_env,
    graph_write_max_global_concurrency_from_env,
    graph_write_max_project_concurrency_from_env,
    graph_write_timeout_seconds_from_env,
)
from memwing.application.access_service import MemoryAccessService
from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.application.gateway_service import MemoryGateway
from memwing.application.lifecycle_service import LifecycleTransitionService
from memwing.application.long_term_filter_service import LongTermFilterService
from memwing.application.control_service import ControlService
from memwing.application.outbox_job_catalog import source_event_job_types
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
from memwing.infrastructure.runtime_backends import (
    RuntimeBackendsHandle,
    close_optional,
    create_api_backends,
    create_pipeline_backends,
)
from memwing.infrastructure.platforms.feishu_openapi import FeishuOpenApiPushSender
from memwing.infrastructure.platforms.feishu_push import FeishuPushDispatcher
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort
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
    extra_backends: tuple[RuntimeBackendsHandle, ...] = ()

    async def close(self) -> None:
        for backends in self.extra_backends:
            await backends.close()
        await close_optional(self.evidence_index)
        await close_optional(self.graph_backend)
        await self.connection.close()


@dataclass(frozen=True, slots=True)
class MemWingWorkerRuntimeHandle:
    runner: MemWingWorkerRunner
    connection: PooledPostgresConnection
    graph_backend: GraphBackendPort | None = None
    evidence_index: EvidenceIndexPort | None = None

    async def close(self) -> None:
        await close_optional(self.evidence_index)
        await close_optional(self.graph_backend)
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
            outbox_job_types=source_event_job_types(auto_push_enabled=auto_push_enabled),
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
    env: Mapping[str, str] | None = None,
    auto_push_enabled: bool = False,
    benchmark_backends: RuntimeBackendsHandle | None = None,
) -> OpenClawRuntimeHandle:
    connection = await PooledPostgresConnection.connect(
        database_url,
        min_size=min_size,
        max_size=max_size,
    )
    created_benchmark_backends: RuntimeBackendsHandle | None = None
    try:
        await ensure_postgres_schema_compatibility(connection)
        store = PostgresDataStore(connection)
        runtime = create_openclaw_adapter_from_store(
            store,
            graph_backend=graph_backend,
            evidence_index=evidence_index,
            auto_push_enabled=auto_push_enabled,
        )
        if benchmark_admin_enabled:
            created_benchmark_backends = benchmark_backends or create_pipeline_backends(env, store)
        benchmark_admin = (
            _benchmark_admin_service(
                store=store,
                connection=connection,
                backends=created_benchmark_backends,
                env=env,
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
        if created_benchmark_backends is not None:
            await created_benchmark_backends.close()
        await connection.close()
        raise
    extra_backends = (
        (created_benchmark_backends,)
        if created_benchmark_backends is not None
        else ()
    )
    return OpenClawRuntimeHandle(
        runtime=runtime,
        connection=connection,
        graph_backend=graph_backend,
        evidence_index=evidence_index,
        benchmark_admin=benchmark_admin,
        pipeline_readiness=pipeline_readiness,
        extra_backends=extra_backends,
    )


async def create_openclaw_adapter_from_env(
    env: Mapping[str, str] | None = None,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> OpenClawRuntimeHandle:
    backends = create_api_backends(env)
    try:
        return await create_openclaw_adapter_from_postgres(
            database_url_from_env(env),
            min_size=min_size,
            max_size=max_size,
            graph_backend=backends.graph_backend,
            evidence_index=backends.evidence_index,
            auto_push_enabled=auto_push_enabled_from_env(env),
        )
    except Exception:
        await backends.close()
        raise


async def create_openclaw_adapter_with_benchmark_admin_from_env(
    env: Mapping[str, str] | None = None,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> OpenClawRuntimeHandle:
    connection = await PooledPostgresConnection.connect(
        database_url_from_env(env),
        min_size=min_size,
        max_size=max_size,
    )
    api_backends: RuntimeBackendsHandle | None = None
    pipeline_backends: RuntimeBackendsHandle | None = None
    try:
        await ensure_postgres_schema_compatibility(connection)
        store = PostgresDataStore(connection)
        api_backends = create_api_backends(env)
        pipeline_backends = create_pipeline_backends(env, store)
        runtime = create_openclaw_adapter_from_store(
            store,
            graph_backend=api_backends.graph_backend,
            evidence_index=api_backends.evidence_index,
            auto_push_enabled=auto_push_enabled_from_env(env),
        )
        benchmark_admin = _benchmark_admin_service(
            store=store,
            connection=connection,
            backends=pipeline_backends,
            env=env,
        )
        pipeline_readiness = PipelineReadinessService(
            store,
            evidence_enabled=pipeline_backends.evidence_index is not None,
            graph_enabled=pipeline_backends.graph_backend is not None,
        )
    except Exception:
        if pipeline_backends is not None:
            await pipeline_backends.close()
        if api_backends is not None:
            await api_backends.close()
        await connection.close()
        raise
    return OpenClawRuntimeHandle(
        runtime=runtime,
        connection=connection,
        graph_backend=api_backends.graph_backend,
        evidence_index=api_backends.evidence_index,
        benchmark_admin=benchmark_admin,
        pipeline_readiness=pipeline_readiness,
        extra_backends=(pipeline_backends,),
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
        backends = create_pipeline_backends(env, store)
        runner = _worker_runner_from_store(
            store,
            backends=backends,
            env=env,
            worker_id=worker_id,
        )
        return MemWingWorkerRuntimeHandle(
            runner=runner,
            connection=_NoopConnection(),
            graph_backend=backends.graph_backend,
            evidence_index=backends.evidence_index,
        )
    connection = await PooledPostgresConnection.connect(
        database_url_from_env(env),
        min_size=min_size,
        max_size=max_size,
    )
    backends: RuntimeBackendsHandle | None = None
    try:
        await ensure_postgres_schema_compatibility(connection)
        store = PostgresDataStore(connection)
        backends = create_pipeline_backends(env, store)
        runner = _worker_runner_from_store(
            store,
            backends=backends,
            env=env,
            worker_id=worker_id,
        )
    except Exception:
        if backends is not None:
            await backends.close()
        await connection.close()
        raise
    return MemWingWorkerRuntimeHandle(
        runner=runner,
        connection=connection,
        graph_backend=backends.graph_backend,
        evidence_index=backends.evidence_index,
    )


def _worker_runner_from_store(
    store: EventStoreUnitOfWorkPort,
    *,
    backends: RuntimeBackendsHandle,
    env: Mapping[str, str] | None,
    worker_id: str,
) -> MemWingWorkerRunner:
    scope_resolver = ScopeResolver(store)
    lifecycle_transition = LifecycleTransitionService(store)
    long_term_filter = LongTermFilterService(
        store,
        _require_long_term_filter_adapter(backends),
        lifecycle_transition=lifecycle_transition,
    )
    page_memory_worker = PageMemoryWorker(
        store,
        PageMemoryService(
            store,
            _require_page_memory_synthesis_adapter(backends),
        ),
        scope_resolver=scope_resolver,
    )
    graph_write_worker = (
        GraphWriteWorker(
            store,
            graph_backend=backends.graph_backend,
            lifecycle_transition=lifecycle_transition,
            worker_id=f"{worker_id}:graph",
            backend_timeout=timedelta(seconds=graph_write_timeout_seconds_from_env(env)),
            batch_size=graph_write_batch_size_from_env(env),
            max_project_concurrency=graph_write_max_project_concurrency_from_env(env),
            max_global_concurrency=graph_write_max_global_concurrency_from_env(env),
        )
        if backends.graph_backend is not None
        else None
    )
    derived_outbox_worker = DerivedOutboxWorker(
        store,
        evidence_index=backends.evidence_index,
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

def _benchmark_admin_service(
    *,
    store: EventStoreUnitOfWorkPort,
    connection: PooledPostgresConnection,
    backends: RuntimeBackendsHandle,
    env: Mapping[str, str] | None,
) -> BenchmarkAdminService:
    scope_resolver = ScopeResolver(store)
    lifecycle_transition = LifecycleTransitionService(store)
    long_term_filter = LongTermFilterService(
        store,
        _require_long_term_filter_adapter(backends),
        lifecycle_transition=lifecycle_transition,
    )
    page_memory_worker = PageMemoryWorker(
        store,
        PageMemoryService(
            store,
            _require_page_memory_synthesis_adapter(backends),
        ),
        scope_resolver=scope_resolver,
    )
    graph_write_worker = (
        GraphWriteWorker(
            store,
            graph_backend=backends.graph_backend,
            lifecycle_transition=lifecycle_transition,
            worker_id="benchmark_graph_write",
            retry_delay=timedelta(0),
            backend_timeout=timedelta(seconds=graph_write_timeout_seconds_from_env(env)),
            batch_size=graph_write_batch_size_from_env(env),
            max_project_concurrency=graph_write_max_project_concurrency_from_env(env),
            max_global_concurrency=graph_write_max_global_concurrency_from_env(env),
        )
        if backends.graph_backend is not None
        else None
    )
    drain_worker = BenchmarkDrainWorker(
        store,
        evidence_index=backends.evidence_index,
        long_term_filter=long_term_filter,
        page_memory_worker=page_memory_worker,
        graph_write_worker=graph_write_worker,
    )
    return BenchmarkAdminService(
        unit_of_work=store,
        admin_store=PostgresBenchmarkAdminStore(connection),
        drain_worker=drain_worker,
        graph_backend=backends.graph_backend,
        evidence_index=backends.evidence_index,
    )


def _require_long_term_filter_adapter(backends: RuntimeBackendsHandle):
    if backends.long_term_filter is None:
        raise RuntimeError("pipeline runtime requires long term filter adapter")
    return backends.long_term_filter


def _require_page_memory_synthesis_adapter(backends: RuntimeBackendsHandle):
    if backends.page_memory_synthesis is None:
        raise RuntimeError("pipeline runtime requires page memory synthesis adapter")
    return backends.page_memory_synthesis


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
