import asyncio

import pytest

from memwing.infrastructure.llm.errors import LLMOutputSchemaError, LLMProviderError
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawCommandResult,
    OpenClawRuntimeConfig,
    OpenClawRuntimeEmbeddingClient,
)
from memwing.ports.model_runtime import MemWingModelSelection


class FakeOpenClawTransport:
    def __init__(self, result: OpenClawCommandResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def run(self, *, command, cwd, env, timeout_seconds):
        self.calls.append(
            {
                "command": tuple(command),
                "cwd": cwd,
                "env": dict(env) if env is not None else None,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.result


def test_openclaw_runtime_embedding_client_runs_embedding_through_cli() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=0,
            stdout=(
                '{"ok":true,"outputs":['
                '{"text":"hello","embedding":[1,0.5],"dimensions":2},'
                '{"text":"world","embedding":[0.25,-0.75],"dimensions":2}'
                "]}"
            ),
            stderr="",
        )
    )
    client = OpenClawRuntimeEmbeddingClient(
        OpenClawRuntimeConfig(
            command="pnpm",
            command_args=("openclaw",),
            cwd="/repo/openclaw",
            model="ollama/qwen3-embedding:0.6b",
            transport="local",
            timeout_seconds=30,
            env={"OLLAMA_API_KEY": "ollama-local"},
        ),
        transport=transport,
    )

    vectors = asyncio.run(client.embed_batch(("hello", "world")))

    assert vectors == ((1.0, 0.5), (0.25, -0.75))
    assert transport.calls == [
        {
            "command": (
                "pnpm",
                "openclaw",
                "capability",
                "embedding",
                "create",
                "--json",
                "--text",
                "hello",
                "--text",
                "world",
                "--model",
                "ollama/qwen3-embedding:0.6b",
            ),
            "cwd": "/repo/openclaw",
            "env": {"OLLAMA_API_KEY": "ollama-local"},
            "timeout_seconds": 30,
        }
    ]


def test_openclaw_runtime_embedding_client_embed_returns_single_vector() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=0,
            stdout='{"ok":true,"outputs":[{"text":"hello","embedding":[0.1,0.2]}]}',
            stderr="",
        )
    )
    client = OpenClawRuntimeEmbeddingClient(OpenClawRuntimeConfig(), transport=transport)

    vector = asyncio.run(client.embed("hello"))

    assert vector == (0.1, 0.2)


def test_openclaw_runtime_embedding_client_noops_empty_batch() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(returncode=0, stdout='{"ok":true,"outputs":[]}', stderr="")
    )
    client = OpenClawRuntimeEmbeddingClient(OpenClawRuntimeConfig(), transport=transport)

    vectors = asyncio.run(client.embed_batch(()))

    assert vectors == ()
    assert transport.calls == []


def test_openclaw_runtime_embedding_client_rejects_gateway_transport() -> None:
    with pytest.raises(ValueError, match="supports local transport only"):
        OpenClawRuntimeEmbeddingClient(OpenClawRuntimeConfig(transport="gateway"))


def test_openclaw_runtime_embedding_client_maps_cli_failure_without_leaking_output() -> None:
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=1,
            stdout='{"token":"secret"}',
            stderr="provider returned token secret",
        )
    )
    client = OpenClawRuntimeEmbeddingClient(OpenClawRuntimeConfig(), transport=transport)

    with pytest.raises(LLMProviderError, match="exit code 1") as exc_info:
        asyncio.run(client.embed("hello"))

    assert "secret" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("stdout", "message"),
    (
        ('{"ok":true}', "requires outputs"),
        ('{"ok":true,"outputs":[]}', "count mismatch"),
        ('{"ok":true,"outputs":[{"text":"other","embedding":[1]}]}', "text mismatch"),
        ('{"ok":true,"outputs":[{"text":"hello","embedding":[]}]}', "requires embedding"),
        ('{"ok":true,"outputs":[{"text":"hello","embedding":["bad"]}]}', "must be numeric"),
    ),
)
def test_openclaw_runtime_embedding_client_rejects_malformed_payload(
    stdout: str,
    message: str,
) -> None:
    transport = FakeOpenClawTransport(OpenClawCommandResult(returncode=0, stdout=stdout, stderr=""))
    client = OpenClawRuntimeEmbeddingClient(OpenClawRuntimeConfig(), transport=transport)

    with pytest.raises(LLMOutputSchemaError, match=message):
        asyncio.run(client.embed("hello"))


def test_openclaw_runtime_embedding_client_from_env_uses_embedding_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCLAW_CLI", "pnpm")
    monkeypatch.setenv("OPENCLAW_CLI_ARGS", "openclaw")
    monkeypatch.setenv("OPENCLAW_CLI_CWD", "/repo/openclaw")
    monkeypatch.setenv("MEMWING_OPENCLAW_MODEL", "text-model")
    monkeypatch.setenv("MEMWING_OPENCLAW_EMBEDDING_MODEL", "ollama/qwen3-embedding:0.6b")
    monkeypatch.setenv("MEMWING_OPENCLAW_EMBEDDING_TRANSPORT", "local")
    monkeypatch.setenv("MEMWING_OPENCLAW_EMBEDDING_TIMEOUT_SECONDS", "45")

    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=0,
            stdout='{"ok":true,"outputs":[{"text":"hello","embedding":[1]}]}',
            stderr="",
        )
    )
    client = OpenClawRuntimeEmbeddingClient.from_env(
        transport=transport,
    )

    asyncio.run(client.embed("hello"))

    assert transport.calls[0]["command"] == (
        "pnpm",
        "openclaw",
        "capability",
        "embedding",
        "create",
        "--json",
        "--text",
        "hello",
        "--model",
        "ollama/qwen3-embedding:0.6b",
    )
    assert transport.calls[0]["timeout_seconds"] == 45


def test_openclaw_runtime_embedding_client_from_model_selection() -> None:
    selection = MemWingModelSelection(
        role="graphiti_embedding",
        runtime="openclaw",
        model="ollama/qwen3-embedding:0.6b",
        transport="local",
        timeout_seconds=25,
    )
    transport = FakeOpenClawTransport(
        OpenClawCommandResult(
            returncode=0,
            stdout='{"ok":true,"outputs":[{"text":"hello","embedding":[1]}]}',
            stderr="",
        )
    )

    client = OpenClawRuntimeEmbeddingClient.from_model_selection(
        selection,
        command="pnpm",
        command_args=("openclaw",),
        cwd="/repo/openclaw",
        env={"OLLAMA_API_KEY": "ollama-local"},
        transport=transport,
    )

    asyncio.run(client.embed("hello"))

    assert transport.calls[0]["command"] == (
        "pnpm",
        "openclaw",
        "capability",
        "embedding",
        "create",
        "--json",
        "--text",
        "hello",
        "--model",
        "ollama/qwen3-embedding:0.6b",
    )
