from __future__ import annotations

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
