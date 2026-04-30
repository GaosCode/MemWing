from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
import shlex
from typing import Literal, Protocol

from memwing.infrastructure.llm.errors import LLMOutputSchemaError, LLMProviderError
from memwing.infrastructure.llm.model_client import LLMModelClient, LLMModelRequest, LLMModelResponse


OpenClawRuntimeTransportMode = Literal["local", "gateway"]


@dataclass(frozen=True, slots=True)
class OpenClawRuntimeConfig:
    command: str = "openclaw"
    command_args: tuple[str, ...] = ()
    cwd: str | None = None
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


@dataclass(frozen=True, slots=True)
class OpenClawCommandResult:
    returncode: int
    stdout: str
    stderr: str


class OpenClawRuntimeTransport(Protocol):
    async def run(
        self,
        *,
        command: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout_seconds: float,
    ) -> OpenClawCommandResult:
        ...


class OpenClawRuntimeLLMClient(LLMModelClient):
    def __init__(
        self,
        config: OpenClawRuntimeConfig,
        *,
        transport: OpenClawRuntimeTransport | None = None,
    ) -> None:
        if not config.command.strip():
            raise ValueError("OpenClaw command is required")
        if config.model is not None and not config.model.strip():
            raise ValueError("OpenClaw model must be non-empty when provided")
        if config.timeout_seconds <= 0:
            raise ValueError("OpenClaw timeout_seconds must be positive")
        self._config = config
        self._transport = transport or SubprocessOpenClawRuntimeTransport()

    @classmethod
    def from_env(
        cls,
        *,
        prefix: str = "MEMWING_OPENCLAW",
        transport: OpenClawRuntimeTransport | None = None,
    ) -> OpenClawRuntimeLLMClient:
        return cls(OpenClawRuntimeConfig.from_env(prefix=prefix), transport=transport)

    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        result = await self._transport.run(
            command=self._command(request),
            cwd=self._config.cwd,
            env=self._config.env,
            timeout_seconds=self._config.timeout_seconds,
        )
        if result.returncode != 0:
            raise LLMProviderError(
                f"OpenClaw runtime model run failed with exit code {result.returncode}"
            )

        payload = _parse_cli_json(result.stdout)
        text = _output_text(payload)
        provider = _optional_text(payload.get("provider")) or "openclaw"
        model = _optional_text(payload.get("model")) or self._config.model or "openclaw"
        return LLMModelResponse(text=text, provider=provider, model=model)

    def _command(self, request: LLMModelRequest) -> tuple[str, ...]:
        command = [
            self._config.command,
            *self._config.command_args,
            "capability",
            "model",
            "run",
            "--prompt",
            _prompt_text(request),
            "--json",
        ]
        if self._config.model is not None:
            command.extend(("--model", self._config.model))
        command.append(f"--{self._config.transport}")
        return tuple(command)


class SubprocessOpenClawRuntimeTransport:
    async def run(
        self,
        *,
        command: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout_seconds: float,
    ) -> OpenClawCommandResult:
        process_env = None if env is None else {**os.environ, **env}
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=process_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise LLMProviderError("OpenClaw runtime command failed to start") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise LLMProviderError("OpenClaw runtime model run timed out") from exc

        return OpenClawCommandResult(
            returncode=process.returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )


def _prompt_text(request: LLMModelRequest) -> str:
    system_prompt = request.system_prompt.strip()
    user_prompt = request.user_prompt.strip()
    if system_prompt:
        return f"System:\n{system_prompt}\n\nUser:\n{user_prompt}"
    return user_prompt


def _parse_cli_json(stdout: str) -> Mapping[str, object]:
    stripped = stdout.strip()
    if not stripped:
        raise LLMOutputSchemaError("OpenClaw runtime returned empty output")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = _parse_last_json_object(stripped)
    if not isinstance(parsed, dict):
        raise LLMOutputSchemaError("OpenClaw runtime output must be a JSON object")
    return parsed


def _parse_last_json_object(stdout: str) -> object:
    decoder = json.JSONDecoder()
    parsed_objects: list[object] = []
    start = 0
    while True:
        start = stdout.find("{", start)
        if start == -1:
            break
        try:
            parsed, end = decoder.raw_decode(stdout[start:])
        except json.JSONDecodeError:
            start += 1
            continue
        parsed_objects.append(parsed)
        start += end
    for parsed in reversed(parsed_objects):
        if isinstance(parsed, dict):
            return parsed
    raise LLMOutputSchemaError("OpenClaw runtime returned invalid JSON")


def _output_text(payload: Mapping[str, object]) -> str:
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        raise LLMOutputSchemaError("OpenClaw runtime output requires outputs")
    text_parts = [
        output.get("text")
        for output in outputs
        if isinstance(output, dict) and isinstance(output.get("text"), str)
    ]
    text = "".join(text_parts).strip()
    if not text:
        raise LLMOutputSchemaError("OpenClaw runtime output requires text output")
    return text


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


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
