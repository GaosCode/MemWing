import asyncio

import pytest

from memwing.infrastructure.llm.errors import LLMOutputSchemaError, LLMProviderError
from memwing.infrastructure.llm.model_client import LLMModelRequest
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawCommandResult,
    OpenClawRuntimeConfig,
    OpenClawRuntimeLLMClient,
)
from memwing.ports.model_runtime import MemWingModelSelection


class FakeOpenClawTransport:
    def __init__(self, result: OpenClawCommandResult | list[OpenClawCommandResult]) -> None:
        self.results = [result] if isinstance(result, OpenClawCommandResult) else result
        self.calls: list[dict[str, object]] = []

    async def run(self, *, command, cwd, env, timeout_seconds):
        result = self.results[min(len(self.calls), len(self.results) - 1)]
        self.calls.append(
            {
                "command": tuple(command),
                "cwd": cwd,
                "env": dict(env) if env is not None else None,
                "timeout_seconds": timeout_seconds,
            }
        )
        return result


def test_openclaw_runtime_client_runs_model_probe_through_cli() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=0,
            stdout='{"ok":true,"provider":"openai","model":"gpt-5","outputs":[{"text":"{\\"ok\\":true}"}]}',
            stderr="",
        )
    )
    client = OpenClawRuntimeLLMClient(
        OpenClawRuntimeConfig(
            command="pnpm",
            command_args=("openclaw",),
            cwd="/repo/openclaw",
            model="openai/gpt-5",
            transport="gateway",
            timeout_seconds=30,
            env={"OPENCLAW_GATEWAY_PORT": "18789"},
        ),
        transport=transport,
    )

    async def scenario():
        return await client.complete(
            LLMModelRequest(
                system_prompt="Return JSON only.",
                user_prompt="Ping",
                trace_id="trace_001",
            )
        )

    response = asyncio.run(scenario())

    assert response.text == '{"ok":true}'
    assert response.provider == "openai"
    assert response.model == "gpt-5"
    assert transport.calls == [
        {
            "command": (
                "pnpm",
                "openclaw",
                "capability",
                "model",
                "run",
                "--prompt",
                "System:\nReturn JSON only.\n\nUser:\nPing",
                "--json",
                "--model",
                "openai/gpt-5",
                "--gateway",
            ),
            "cwd": "/repo/openclaw",
            "env": {"OPENCLAW_GATEWAY_PORT": "18789"},
            "timeout_seconds": 30,
        }
    ]


def test_openclaw_runtime_client_parses_last_json_line() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=0,
            stdout='status: ready\n{"ok":true,"outputs":[{"text":"done"}]}\n',
            stderr="",
        )
    )
    client = OpenClawRuntimeLLMClient(OpenClawRuntimeConfig(), transport=transport)

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="", user_prompt="Ping", trace_id=None)
        )

    response = asyncio.run(scenario())

    assert response.text == "done"
    assert response.provider == "openclaw"
    assert response.model == "openclaw"


def test_openclaw_runtime_client_parses_pretty_json_after_cli_banner() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=0,
            stdout="""
> openclaw@2026.4.27 openclaw /repo/openclaw
> node scripts/run-node.mjs capability model run --prompt "Return {\\"ok\\": true}" --json

{
  "ok": true,
  "provider": "openai",
  "model": "gpt-5",
  "outputs": [
    {
      "text": "{\\"ok\\": true}",
      "mediaUrl": null
    }
  ]
}
""",
            stderr="",
        )
    )
    client = OpenClawRuntimeLLMClient(OpenClawRuntimeConfig(), transport=transport)

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="", user_prompt="Ping", trace_id=None)
        )

    response = asyncio.run(scenario())

    assert response.text == '{"ok": true}'
    assert response.provider == "openai"
    assert response.model == "gpt-5"


def test_openclaw_runtime_client_maps_cli_failure_without_leaking_output() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=1,
            stdout='{"token":"secret"}',
            stderr="provider returned token secret",
        )
    )
    client = OpenClawRuntimeLLMClient(OpenClawRuntimeConfig(), transport=transport)

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="", user_prompt="Ping", trace_id=None)
        )

    with pytest.raises(LLMProviderError, match="exit code 1") as exc_info:
        asyncio.run(scenario())

    assert "secret" not in str(exc_info.value)
    assert "stdout_summary=" in str(exc_info.value)
    assert "stdout_len=" in str(exc_info.value)


def test_openclaw_runtime_client_retries_empty_text_output_failure() -> None:
    transport = FakeOpenClawTransport(
        [
            OpenClawCommandResult(
                returncode=1,
                stdout='{"ok":true,"outputs":[]}',
                stderr='Error: No text output returned for provider "volcengine" model "current".',
            ),
            OpenClawCommandResult(
                returncode=0,
                stdout='{"ok":true,"provider":"volcengine","model":"current","outputs":[{"text":"done"}]}',
                stderr="",
            ),
        ]
    )
    client = OpenClawRuntimeLLMClient(OpenClawRuntimeConfig(), transport=transport)

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="", user_prompt="Ping", trace_id=None)
        )

    response = asyncio.run(scenario())

    assert response.text == "done"
    assert len(transport.calls) == 2


def test_openclaw_runtime_client_does_not_retry_generic_cli_failure() -> None:
    transport = FakeOpenClawTransport(
        [
            OpenClawCommandResult(
                returncode=1,
                stdout="",
                stderr="provider rate limit",
            ),
            OpenClawCommandResult(
                returncode=0,
                stdout='{"ok":true,"outputs":[{"text":"done"}]}',
                stderr="",
            ),
        ]
    )
    client = OpenClawRuntimeLLMClient(OpenClawRuntimeConfig(), transport=transport)

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="", user_prompt="Ping", trace_id=None)
        )

    with pytest.raises(LLMProviderError, match="provider rate limit"):
        asyncio.run(scenario())

    assert len(transport.calls) == 1


def test_openclaw_runtime_client_reports_empty_output_after_retries() -> None:
    empty_output = OpenClawCommandResult(
        returncode=1,
        stdout='{"ok":true,"outputs":[]}',
        stderr='Error: No text output returned for provider "volcengine" model "current".',
    )
    transport = FakeOpenClawTransport([empty_output, empty_output, empty_output])
    client = OpenClawRuntimeLLMClient(OpenClawRuntimeConfig(), transport=transport)

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="", user_prompt="Ping", trace_id=None)
        )

    with pytest.raises(LLMProviderError) as exc_info:
        asyncio.run(scenario())

    message = str(exc_info.value)
    assert "failed after 3 empty-output attempts" in message
    assert "stdout_summary=" in message
    assert "stdout_len=" in message
    assert len(transport.calls) == 3


def test_openclaw_runtime_client_rejects_malformed_payload() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=0,
            stdout='{"ok":true,"outputs":[]}',
            stderr="",
        )
    )
    client = OpenClawRuntimeLLMClient(OpenClawRuntimeConfig(), transport=transport)

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="", user_prompt="Ping", trace_id=None)
        )

    with pytest.raises(LLMOutputSchemaError, match="requires text output"):
        asyncio.run(scenario())


def test_openclaw_runtime_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_CLI", "pnpm")
    monkeypatch.setenv("OPENCLAW_CLI_ARGS", "openclaw --profile dev")
    monkeypatch.setenv("OPENCLAW_CLI_CWD", "/repo/openclaw")
    monkeypatch.setenv("MEMWING_OPENCLAW_MODEL", "anthropic/claude-sonnet-4-6")
    monkeypatch.setenv("MEMWING_OPENCLAW_TRANSPORT", "local")
    monkeypatch.setenv("MEMWING_OPENCLAW_TIMEOUT_SECONDS", "45")

    config = OpenClawRuntimeConfig.from_env()

    assert config.command == "pnpm"
    assert config.command_args == ("openclaw", "--profile", "dev")
    assert config.cwd == "/repo/openclaw"
    assert config.model == "anthropic/claude-sonnet-4-6"
    assert config.transport == "local"
    assert config.timeout_seconds == 45


def test_openclaw_runtime_config_from_model_selection() -> None:
    selection = MemWingModelSelection(
        role="graphiti_extraction",
        runtime="openclaw",
        model="current",
        transport="gateway",
        timeout_seconds=25,
    )

    config = OpenClawRuntimeConfig.from_model_selection(
        selection,
        command="pnpm",
        command_args=("openclaw",),
        cwd="/repo/openclaw",
        env={"OPENCLAW_GATEWAY_PORT": "18789"},
    )

    assert config.command == "pnpm"
    assert config.command_args == ("openclaw",)
    assert config.cwd == "/repo/openclaw"
    assert config.role == "graphiti_extraction"
    assert config.model == "current"
    assert config.transport == "gateway"
    assert config.timeout_seconds == 25
    assert config.env == {"OPENCLAW_GATEWAY_PORT": "18789"}


def test_openclaw_runtime_config_from_env_model_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = MemWingModelSelection(
        role="page_memory",
        runtime="openclaw",
        model="ollama/qwen3.5:4b",
        transport="local",
        timeout_seconds=25,
    )
    monkeypatch.setenv("OPENCLAW_CLI", "pnpm")
    monkeypatch.setenv("OPENCLAW_CLI_ARGS", "openclaw --profile dev")
    monkeypatch.setenv("OPENCLAW_CLI_CWD", "/repo/openclaw")

    config = OpenClawRuntimeConfig.from_env_model_selection(
        selection,
        env={"OLLAMA_API_KEY": "ollama-local"},
    )

    assert config.command == "pnpm"
    assert config.command_args == ("openclaw", "--profile", "dev")
    assert config.cwd == "/repo/openclaw"
    assert config.role == "page_memory"
    assert config.model == "ollama/qwen3.5:4b"
    assert config.transport == "local"
    assert config.env == {"OLLAMA_API_KEY": "ollama-local"}


def test_openclaw_runtime_config_requires_openclaw_selection() -> None:
    selection = MemWingModelSelection(
        role="page_memory",
        runtime="openai_compatible",
        model="gpt-5",
        transport=None,
        timeout_seconds=60,
    )

    with pytest.raises(ValueError, match="requires openclaw runtime"):
        OpenClawRuntimeConfig.from_model_selection(selection)
