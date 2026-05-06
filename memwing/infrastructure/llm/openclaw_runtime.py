from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
import os
import re
import signal
import shlex
import sys
import tempfile
from typing import Literal, Protocol

from memwing.infrastructure.llm.errors import LLMOutputSchemaError, LLMProviderError
from memwing.infrastructure.llm.embedding_client import EmbeddingModelClient
from memwing.infrastructure.llm.model_client import (
    LLMModelClient,
    LLMModelRequest,
    LLMModelResponse,
)
from memwing.ports.model_runtime import MemWingModelRole, MemWingModelSelection, ModelCacheContext


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
    _MAX_EMPTY_OUTPUT_ATTEMPTS = 3

    def __init__(
        self,
        config: OpenClawRuntimeConfig,
        *,
        transport: OpenClawRuntimeTransport | None = None,
    ) -> None:
        _validate_runtime_config(config)
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

    @classmethod
    def from_model_selection(
        cls,
        selection: MemWingModelSelection,
        *,
        command: str = "openclaw",
        command_args: tuple[str, ...] = (),
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        transport: OpenClawRuntimeTransport | None = None,
    ) -> OpenClawRuntimeLLMClient:
        return cls(
            OpenClawRuntimeConfig.from_model_selection(
                selection,
                command=command,
                command_args=command_args,
                cwd=cwd,
                env=env,
            ),
            transport=transport,
        )

    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        result: OpenClawCommandResult | None = None
        for attempt in range(self._MAX_EMPTY_OUTPUT_ATTEMPTS):
            result = await self._transport.run(
                command=self._command(request),
                cwd=self._config.cwd,
                env=self._config.env,
                timeout_seconds=self._config.timeout_seconds,
            )
            if result.returncode == 0:
                break
            if not _is_empty_text_output_failure(result):
                raise LLMProviderError(_command_failure_message("model run", result))
            if attempt == self._MAX_EMPTY_OUTPUT_ATTEMPTS - 1:
                raise LLMProviderError(
                    _command_failure_message(
                        f"model run failed after {self._MAX_EMPTY_OUTPUT_ATTEMPTS} empty-output attempts",
                        result,
                    )
                )
            _debug_log(
                "OpenClaw model run returned no text output; retrying "
                f"attempt={attempt + 2}/{self._MAX_EMPTY_OUTPUT_ATTEMPTS}"
            )
        if result is None:
            raise LLMProviderError("OpenClaw runtime model run did not execute")

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


class OpenClawRuntimeEmbeddingClient(EmbeddingModelClient):
    def __init__(
        self,
        config: OpenClawRuntimeConfig,
        *,
        transport: OpenClawRuntimeTransport | None = None,
    ) -> None:
        _validate_runtime_config(config)
        if config.transport != "local":
            raise ValueError("OpenClaw embedding runtime currently supports local transport only")
        self._config = config
        self._transport = transport or SubprocessOpenClawRuntimeTransport()

    @classmethod
    def from_env(
        cls,
        *,
        prefix: str = "MEMWING_OPENCLAW_EMBEDDING",
        transport: OpenClawRuntimeTransport | None = None,
    ) -> OpenClawRuntimeEmbeddingClient:
        return cls(OpenClawRuntimeConfig.from_env(prefix=prefix), transport=transport)

    @classmethod
    def from_model_selection(
        cls,
        selection: MemWingModelSelection,
        *,
        command: str = "openclaw",
        command_args: tuple[str, ...] = (),
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        transport: OpenClawRuntimeTransport | None = None,
    ) -> OpenClawRuntimeEmbeddingClient:
        return cls(
            OpenClawRuntimeConfig.from_model_selection(
                selection,
                command=command,
                command_args=command_args,
                cwd=cwd,
                env=env,
            ),
            transport=transport,
        )

    async def embed(
        self,
        input: str,
        *,
        cache_context: ModelCacheContext | None = None,
    ) -> tuple[float, ...]:
        return (
            await self.embed_batch(
                (input,),
                cache_contexts=(cache_context,),
            )
        )[0]

    async def embed_batch(
        self,
        inputs: tuple[str, ...],
        *,
        cache_contexts: tuple[ModelCacheContext | None, ...] | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        if not inputs:
            return ()
        result = await self._transport.run(
            command=self._command(inputs),
            cwd=self._config.cwd,
            env=self._config.env,
            timeout_seconds=self._config.timeout_seconds,
        )
        if result.returncode != 0:
            raise LLMProviderError(_command_failure_message("embedding run", result))

        payload = _parse_cli_json(result.stdout)
        return _embedding_outputs(payload, expected_texts=inputs)

    def _command(self, inputs: tuple[str, ...]) -> tuple[str, ...]:
        command = [
            self._config.command,
            *self._config.command_args,
            "capability",
            "embedding",
            "create",
            "--json",
        ]
        for input_text in inputs:
            command.extend(("--text", input_text))
        if self._config.model is not None:
            command.extend(("--model", self._config.model))
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
        _debug_log(f"OpenClaw subprocess start: cmd={command[0]} cwd={cwd} timeout={timeout_seconds}s")

        def _run_sync() -> tuple[int, bytes, bytes]:
            import subprocess as _subprocess

            # Use a temp file for stdout to avoid pipe hang on macOS Python 3.13
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                stdout_path = tmp.name
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                stderr_path = tmp.name

            try:
                with open(stdout_path, "wb") as out_fh, open(stderr_path, "wb") as err_fh:
                    proc = _subprocess.Popen(
                        tuple(command),
                        cwd=cwd,
                        env=process_env,
                        stdin=_subprocess.DEVNULL,
                        stdout=out_fh,
                        stderr=err_fh,
                        start_new_session=True,
                    )
                    _debug_log(f"OpenClaw pid={proc.pid} waiting (max {timeout_seconds:.0f}s)...")
                    try:
                        proc.wait(timeout=timeout_seconds)
                    except _subprocess.TimeoutExpired:
                        _debug_log(f"OpenClaw pid={proc.pid} TIMEOUT, killing...")
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            proc.kill()
                        proc.wait()
                        raise LLMProviderError("OpenClaw runtime model run timed out")

                with open(stdout_path, "rb") as in_fh:
                    stdout_bytes = in_fh.read()
                with open(stderr_path, "rb") as in_fh:
                    stderr_bytes = in_fh.read()
            finally:
                try:
                    os.unlink(stdout_path)
                except OSError:
                    pass
                try:
                    os.unlink(stderr_path)
                except OSError:
                    pass

            _debug_log(
                f"OpenClaw pid={proc.pid} done rc={proc.returncode} "
                f"out_len={len(stdout_bytes)} err_len={len(stderr_bytes)}"
            )
            return proc.returncode, stdout_bytes, stderr_bytes

        try:
            returncode, stdout_bytes, stderr_bytes = await asyncio.to_thread(_run_sync)
        except LLMProviderError:
            raise
        except OSError as exc:
            _debug_log(f"OpenClaw OSError: {exc}")
            raise LLMProviderError("OpenClaw runtime command failed to start") from exc

        return OpenClawCommandResult(
            returncode=returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )


_DEBUG_OPENCLAW = os.environ.get("MEMWING_DEBUG_OPENCLAW") == "1"


def _debug_log(msg: str) -> None:
    if not _DEBUG_OPENCLAW:
        return
    print(f"[openclaw-runtime] {msg}", file=sys.stderr, flush=True)


def _command_failure_message(label: str, result: OpenClawCommandResult) -> str:
    parts = [f"OpenClaw runtime {label} failed with exit code {result.returncode}"]
    stderr_summary = _safe_process_output_summary(result.stderr)
    if stderr_summary:
        parts.append(f"stderr={stderr_summary}")
    elif result.stderr:
        parts.append(f"stderr_len={len(result.stderr)}")
    if result.stdout:
        stdout_summary = _safe_process_output_summary(result.stdout)
        if stdout_summary:
            parts.append(f"stdout_summary={stdout_summary}")
        parts.append(f"stdout_len={len(result.stdout)}")
    return "; ".join(parts)


def _is_empty_text_output_failure(result: OpenClawCommandResult) -> bool:
    if result.returncode == 0:
        return False
    return "No text output returned" in result.stderr


def _safe_process_output_summary(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = " | ".join(lines[-3:])
    summary = re.sub(r"[\x00-\x1f\x7f]+", " ", summary)
    summary = re.sub(
        r"(?i)(authorization|api[_-]?key|token|password|secret)(\s*[:=]\s*)(\S+)",
        r"\1\2[redacted]",
        summary,
    )
    summary = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", summary)
    summary = re.sub(r"(?i)secret", "[redacted]", summary)
    if len(summary) > 500:
        return f"{summary[:500]}...[truncated]"
    return summary


def _validate_runtime_config(config: OpenClawRuntimeConfig) -> None:
    if not config.command.strip():
        raise ValueError("OpenClaw command is required")
    if config.model is not None and not config.model.strip():
        raise ValueError("OpenClaw model must be non-empty when provided")
    if config.timeout_seconds <= 0:
        raise ValueError("OpenClaw timeout_seconds must be positive")


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


def _embedding_outputs(
    payload: Mapping[str, object],
    *,
    expected_texts: tuple[str, ...],
) -> tuple[tuple[float, ...], ...]:
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        raise LLMOutputSchemaError("OpenClaw runtime embedding output requires outputs")
    if len(outputs) != len(expected_texts):
        raise LLMOutputSchemaError("OpenClaw runtime embedding output count mismatch")

    vectors: list[tuple[float, ...]] = []
    for output, expected_text in zip(outputs, expected_texts, strict=True):
        if not isinstance(output, dict):
            raise LLMOutputSchemaError("OpenClaw runtime embedding output must be an object")
        if output.get("text") != expected_text:
            raise LLMOutputSchemaError("OpenClaw runtime embedding output text mismatch")
        embedding = output.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise LLMOutputSchemaError("OpenClaw runtime embedding output requires embedding")
        vectors.append(_embedding_vector(embedding))
    return tuple(vectors)


def _embedding_vector(embedding: list[object]) -> tuple[float, ...]:
    vector: list[float] = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise LLMOutputSchemaError("OpenClaw runtime embedding values must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise LLMOutputSchemaError("OpenClaw runtime embedding values must be finite")
        vector.append(number)
    return tuple(vector)


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
