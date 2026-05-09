from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
import shlex
from typing import Literal

from memwing.ports.model_runtime import MemWingModelRole, MemWingModelSelection


OpenClawRuntimeTransportMode = Literal["local", "gateway"]


@dataclass(frozen=True, slots=True)
class OpenClawRuntimeConfig:
    command: str = "openclaw"
    command_args: tuple[str, ...] = ()
    cwd: str | None = None
    role: MemWingModelRole | None = None
    model: str | None = None
    transport: OpenClawRuntimeTransportMode = "local"
    timeout_seconds: float = 120.0
    env: Mapping[str, str] | None = None

    @classmethod
    def from_env(cls, *, prefix: str = "MEMWING_OPENCLAW") -> OpenClawRuntimeConfig:
        return cls(
            command=os.environ.get("OPENCLAW_CLI", "openclaw"),
            command_args=tuple(shlex.split(os.environ.get("OPENCLAW_CLI_ARGS", ""))),
            cwd=_optional_env("OPENCLAW_CLI_CWD"),
            model=_optional_env(f"{prefix}_MODEL"),
            transport=_env_transport(f"{prefix}_TRANSPORT"),
            timeout_seconds=float(os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "120")),
        )

    @classmethod
    def from_model_selection(
        cls,
        selection: MemWingModelSelection,
        *,
        command: str = "openclaw",
        command_args: tuple[str, ...] = (),
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> OpenClawRuntimeConfig:
        if selection.runtime != "openclaw":
            raise ValueError("OpenClaw runtime config requires openclaw runtime")
        transport = selection.transport or "local"
        if transport not in {"local", "gateway"}:
            raise ValueError("OpenClaw runtime transport must be local or gateway")
        return cls(
            command=command,
            command_args=command_args,
            cwd=cwd,
            role=selection.role,
            model=selection.model,
            transport=transport,
            timeout_seconds=selection.timeout_seconds,
            env=env,
        )

    @classmethod
    def from_env_model_selection(
        cls,
        selection: MemWingModelSelection,
        *,
        env: Mapping[str, str] | None = None,
    ) -> OpenClawRuntimeConfig:
        return cls.from_model_selection(
            selection,
            command=os.environ.get("OPENCLAW_CLI", "openclaw"),
            command_args=tuple(shlex.split(os.environ.get("OPENCLAW_CLI_ARGS", ""))),
            cwd=_optional_env("OPENCLAW_CLI_CWD"),
            env=env,
        )


def validate_runtime_config(config: OpenClawRuntimeConfig) -> None:
    if not config.command.strip():
        raise ValueError("OpenClaw command is required")
    if config.model is not None and not config.model.strip():
        raise ValueError("OpenClaw model must be non-empty when provided")
    if config.timeout_seconds <= 0:
        raise ValueError("OpenClaw timeout_seconds must be positive")


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value


def _env_transport(name: str) -> OpenClawRuntimeTransportMode:
    value = os.environ.get(name, "local").strip().lower()
    if value in {"local", "gateway"}:
        return value
    raise ValueError(f"{name} must be local or gateway")
