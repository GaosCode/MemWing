from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from typing import AsyncContextManager

from memwing.api.runtime_config import benchmark_admin_enabled_from_env, feishu_push_config_from_env
from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.application.control_service import ControlService
from memwing.application.pipeline_readiness_service import PipelineReadinessService
from memwing.application.scope_resolver import ScopeResolver
from memwing.application.source_redaction_service import SourceRedactionService
from memwing.bootstrap_scope import ensure_lite_scope, ensure_postgres_scope
from memwing.infrastructure.agents.openclaw_adapter_factory import (
    create_openclaw_adapter_from_env,
    create_openclaw_adapter_with_benchmark_admin_from_env,
    create_openclaw_adapter_from_store,
)
from memwing.infrastructure.db.postgres import PostgresDataStore
from memwing.infrastructure.db.sqlite_store import SQLiteDataStore
from memwing.infrastructure.platforms.feishu_openapi import FeishuOpenApiPushSender
from memwing.infrastructure.platforms.feishu_push import FeishuPushDispatcher
from memwing.ports.agent_runtime import AgentRuntimePort


@dataclass(frozen=True, slots=True)
class MemWingApiRuntimeContext:
    runtime: AgentRuntimePort
    benchmark_admin: BenchmarkAdminService | None = None
    pipeline_readiness: PipelineReadinessService | None = None
    control: ControlService | None = None
    control_scope_resolver: ScopeResolver | None = None
    source_redaction: SourceRedactionService | None = None


@asynccontextmanager
async def postgres_runtime_context() -> AsyncIterator[MemWingApiRuntimeContext]:
    if benchmark_admin_enabled_from_env():
        handle = await create_openclaw_adapter_with_benchmark_admin_from_env()
    else:
        handle = await create_openclaw_adapter_from_env()
    try:
        await ensure_postgres_scope(handle.connection)
        store = PostgresDataStore(handle.connection)
        yield MemWingApiRuntimeContext(
            runtime=handle.runtime,
            benchmark_admin=handle.benchmark_admin,
            pipeline_readiness=handle.pipeline_readiness,
            control=ControlService(store, platform_connectors=_platform_connectors_from_env()),
            control_scope_resolver=ScopeResolver(store),
            source_redaction=SourceRedactionService(store, graph_backend=handle.graph_backend),
        )
    finally:
        await handle.close()


@asynccontextmanager
async def lite_runtime_context() -> AsyncIterator[MemWingApiRuntimeContext]:
    store = SQLiteDataStore.from_path(_lite_db_path())
    await ensure_lite_scope(store)
    yield MemWingApiRuntimeContext(
        runtime=create_openclaw_adapter_from_store(store),
        pipeline_readiness=PipelineReadinessService(
            store,
            evidence_enabled=False,
            graph_enabled=False,
        ),
        control=ControlService(store, platform_connectors=_platform_connectors_from_env()),
        control_scope_resolver=ScopeResolver(store),
        source_redaction=SourceRedactionService(store, graph_backend=None),
    )


def runtime_context_from_env() -> AsyncContextManager[MemWingApiRuntimeContext]:
    if _profile_from_env() == "lite" or _storage_backend_from_env() == "sqlite":
        return lite_runtime_context()
    return postgres_runtime_context()


def _profile_from_env() -> str:
    return os.environ.get("MEMWING_PROFILE", "").strip().casefold()


def _storage_backend_from_env() -> str:
    return os.environ.get("MEMWING_STORAGE_BACKEND", "").strip().casefold()


def _lite_db_path() -> str:
    return os.environ.get("MEMWING_LITE_DB_PATH", "").strip() or "~/.memwing/memwing.db"


def _platform_connectors_from_env() -> dict[str, object]:
    feishu_config = feishu_push_config_from_env()
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


__all__ = (
    "MemWingApiRuntimeContext",
    "lite_runtime_context",
    "postgres_runtime_context",
    "runtime_context_from_env",
)
