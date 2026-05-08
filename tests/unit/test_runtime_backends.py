import asyncio

from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.llm.long_term_filter import MemWingLongTermFilterAdapter
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawRuntimeEmbeddingClient,
    OpenClawRuntimeLLMClient,
)
from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver
from memwing.infrastructure.llm.page_memory_synthesis import MemWingPageMemorySynthesisAdapter
from memwing.infrastructure import runtime_backends
from memwing.infrastructure.runtime_backends import RuntimeBackendsHandle, create_api_backends, create_pipeline_backends


def test_runtime_backends_return_none_for_disabled_graph_and_evidence() -> None:
    backends = create_api_backends(
        {
            "MEMWING_GRAPH_BACKEND": "disabled",
            "MEMWING_EVIDENCE_BACKEND": "disabled",
        }
    )

    assert backends.graph_backend is None
    assert backends.evidence_index is None
    assert backends.long_term_filter is None
    assert backends.page_memory_synthesis is None


def test_pipeline_backends_build_cached_model_adapters_with_store() -> None:
    backends = create_pipeline_backends(
        {
            "MEMWING_GRAPH_BACKEND": "disabled",
            "MEMWING_EVIDENCE_BACKEND": "disabled",
            "MEMWING_MODEL_RUNTIME": "openclaw",
        },
        InMemoryDataStore(),
    )

    assert isinstance(backends.long_term_filter, MemWingLongTermFilterAdapter)
    assert isinstance(backends.page_memory_synthesis, MemWingPageMemorySynthesisAdapter)
    assert backends.long_term_filter._cache is not None
    assert backends.page_memory_synthesis._cache is not None


def test_runtime_backends_close_evidence_before_graph() -> None:
    async def run() -> None:
        calls: list[str] = []
        backends = RuntimeBackendsHandle(
            graph_backend=FakeClosable("graph", calls),
            evidence_index=FakeClosable("evidence", calls),
        )

        await backends.close()

        assert calls == ["evidence", "graph"]

    asyncio.run(run())


def test_runtime_backend_model_clients_use_configured_cli_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_CLI", "pnpm")
    monkeypatch.setenv("OPENCLAW_CLI_ARGS", "openclaw --profile dev")
    monkeypatch.setenv("OPENCLAW_CLI_CWD", "/repo/openclaw")
    resolver = MemWingModelConfigResolver.from_env(
        {
            "MEMWING_MODEL_RUNTIME": "openclaw",
            "MEMWING_MODEL_TRANSPORT": "local",
        }
    )

    llm_client = runtime_backends._llm_client_for_role(resolver, "long_term_filter")
    embedding_client = runtime_backends._embedding_client_for_role(
        resolver,
        "evidence_embedding",
    )

    assert isinstance(llm_client, OpenClawRuntimeLLMClient)
    assert llm_client._config.command == "pnpm"
    assert llm_client._config.command_args == ("openclaw", "--profile", "dev")
    assert llm_client._config.cwd == "/repo/openclaw"
    assert isinstance(embedding_client, OpenClawRuntimeEmbeddingClient)
    assert embedding_client._config.command == "pnpm"
    assert embedding_client._config.command_args == ("openclaw", "--profile", "dev")
    assert embedding_client._config.cwd == "/repo/openclaw"


class FakeClosable:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    async def close(self) -> None:
        self.calls.append(self.name)
