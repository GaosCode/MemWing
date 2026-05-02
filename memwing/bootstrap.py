from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from memwing.infrastructure.agents.openclaw_adapter_factory import create_openclaw_adapter_from_env
from memwing.ports.agent_runtime import AgentRuntimePort


@asynccontextmanager
async def postgres_runtime_context() -> AsyncIterator[AgentRuntimePort]:
    handle = await create_openclaw_adapter_from_env()
    try:
        yield handle.runtime
    finally:
        await handle.close()


__all__ = ("postgres_runtime_context",)
