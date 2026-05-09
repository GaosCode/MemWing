from __future__ import annotations

from collections.abc import Mapping

from memwing.infrastructure.llm.errors import LLMProviderError
from memwing.infrastructure.llm.embedding_client import EmbeddingModelClient
from memwing.infrastructure.llm.model_client import (
    LLMModelClient,
    LLMModelRequest,
    LLMModelResponse,
)
from memwing.infrastructure.llm.openclaw_runtime_config import (
    OpenClawRuntimeConfig,
    OpenClawRuntimeTransportMode,
    validate_runtime_config,
)
from memwing.infrastructure.llm.openclaw_runtime_payloads import (
    command_failure_message,
    embedding_outputs,
    is_empty_text_output_failure,
    optional_text,
    output_text,
    parse_cli_json,
    prompt_text,
)
from memwing.infrastructure.llm.openclaw_runtime_transport import (
    OpenClawCommandResult,
    OpenClawRuntimeTransport,
    SubprocessOpenClawRuntimeTransport,
    debug_log,
)
from memwing.ports.model_runtime import MemWingModelSelection, ModelCacheContext


class OpenClawRuntimeLLMClient(LLMModelClient):
    _MAX_EMPTY_OUTPUT_ATTEMPTS = 3

    def __init__(
        self,
        config: OpenClawRuntimeConfig,
        *,
        transport: OpenClawRuntimeTransport | None = None,
    ) -> None:
        validate_runtime_config(config)
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
            if not is_empty_text_output_failure(result):
                raise LLMProviderError(command_failure_message("model run", result))
            if attempt == self._MAX_EMPTY_OUTPUT_ATTEMPTS - 1:
                raise LLMProviderError(
                    command_failure_message(
                        f"model run failed after {self._MAX_EMPTY_OUTPUT_ATTEMPTS} empty-output attempts",
                        result,
                    )
                )
            debug_log(
                "OpenClaw model run returned no text output; retrying "
                f"attempt={attempt + 2}/{self._MAX_EMPTY_OUTPUT_ATTEMPTS}"
            )
        if result is None:
            raise LLMProviderError("OpenClaw runtime model run did not execute")

        payload = parse_cli_json(result.stdout)
        text = output_text(payload)
        provider = optional_text(payload.get("provider")) or "openclaw"
        model = optional_text(payload.get("model")) or self._config.model or "openclaw"
        return LLMModelResponse(text=text, provider=provider, model=model)

    def _command(self, request: LLMModelRequest) -> tuple[str, ...]:
        command = [
            self._config.command,
            *self._config.command_args,
            "capability",
            "model",
            "run",
            "--prompt",
            prompt_text(request),
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
        validate_runtime_config(config)
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
            raise LLMProviderError(command_failure_message("embedding run", result))

        payload = parse_cli_json(result.stdout)
        return embedding_outputs(payload, expected_texts=inputs)

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


__all__ = [
    "OpenClawCommandResult",
    "OpenClawRuntimeConfig",
    "OpenClawRuntimeEmbeddingClient",
    "OpenClawRuntimeLLMClient",
    "OpenClawRuntimeTransport",
    "OpenClawRuntimeTransportMode",
    "SubprocessOpenClawRuntimeTransport",
]
