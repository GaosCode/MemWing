from __future__ import annotations

from collections.abc import Mapping
import os

from memwing.api.openclaw_mock_runtime import OpenClawMockRuntime
from memwing.ports.agent_runtime import AgentRuntimePort


class OpenClawRuntimeUnavailableError(RuntimeError):
    pass


def resolve_openclaw_runtime(
    runtime: AgentRuntimePort | None,
    *,
    allow_mock_runtime: bool = False,
) -> AgentRuntimePort:
    if runtime is not None:
        return runtime
    if allow_mock_runtime:
        return OpenClawMockRuntime()
    raise OpenClawRuntimeUnavailableError("OpenClaw runtime is not configured")


def database_url_from_env(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    database_url = source.get("DATABASE_URL", "").strip()
    if not database_url:
        raise OpenClawRuntimeUnavailableError("DATABASE_URL is required for Postgres OpenClaw runtime")
    return database_url
