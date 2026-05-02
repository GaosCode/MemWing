from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from memwing.api.runtime_config import benchmark_admin_enabled_from_env
from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.infrastructure.agents.openclaw_adapter_factory import (
    create_openclaw_adapter_from_env,
    create_openclaw_adapter_with_benchmark_admin_from_env,
)
from memwing.ports.agent_runtime import AgentRuntimePort


@dataclass(frozen=True, slots=True)
class MemWingApiRuntimeContext:
    runtime: AgentRuntimePort
    benchmark_admin: BenchmarkAdminService | None = None


@asynccontextmanager
async def postgres_runtime_context() -> AsyncIterator[MemWingApiRuntimeContext]:
    if benchmark_admin_enabled_from_env():
        handle = await create_openclaw_adapter_with_benchmark_admin_from_env()
    else:
        handle = await create_openclaw_adapter_from_env()
    try:
        yield MemWingApiRuntimeContext(
            runtime=handle.runtime,
            benchmark_admin=handle.benchmark_admin,
        )
    finally:
        await handle.close()


__all__ = ("MemWingApiRuntimeContext", "postgres_runtime_context")
