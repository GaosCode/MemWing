from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from memwing.api.runtime_config import benchmark_admin_enabled_from_env
from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.application.control_service import ControlService
from memwing.application.pipeline_readiness_service import PipelineReadinessService
from memwing.application.scope_resolver import ScopeResolver
from memwing.application.source_redaction_service import SourceRedactionService
from memwing.infrastructure.agents.openclaw_adapter_factory import (
    create_openclaw_adapter_from_env,
    create_openclaw_adapter_with_benchmark_admin_from_env,
)
from memwing.infrastructure.db.postgres import PostgresDataStore
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
        store = PostgresDataStore(handle.connection)
        yield MemWingApiRuntimeContext(
            runtime=handle.runtime,
            benchmark_admin=handle.benchmark_admin,
            pipeline_readiness=handle.pipeline_readiness,
            control=ControlService(store),
            control_scope_resolver=ScopeResolver(store),
            source_redaction=SourceRedactionService(store, graph_backend=handle.graph_backend),
        )
    finally:
        await handle.close()


__all__ = ("MemWingApiRuntimeContext", "postgres_runtime_context")
