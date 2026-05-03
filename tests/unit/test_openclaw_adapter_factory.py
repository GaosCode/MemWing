import asyncio

from memwing.infrastructure.agents.openclaw_adapter_factory import (
    OpenClawRuntimeHandle,
    create_openclaw_adapter_from_store,
)
from memwing.infrastructure.agents import openclaw_adapter_factory
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.llm.openclaw_runtime import (
    OpenClawRuntimeEmbeddingClient,
    OpenClawRuntimeLLMClient,
)
from memwing.infrastructure.llm.model_config import MemWingModelConfigResolver


def test_factory_passes_graph_and_evidence_ports_to_memory_access() -> None:
    store = InMemoryDataStore()
    graph_backend = object()
    evidence_index = object()

    adapter = create_openclaw_adapter_from_store(
        store,
        graph_backend=graph_backend,
        evidence_index=evidence_index,
    )

    memory_access = adapter._memory_access
    assert memory_access._current_truth._graph_backend is graph_backend
    assert memory_access._current_truth._evidence_index is evidence_index


def test_runtime_handle_closes_external_clients_before_postgres() -> None:
    async def run() -> None:
        calls: list[str] = []
        handle = OpenClawRuntimeHandle(
            runtime=object(),
            connection=FakeConnection(calls),
            graph_backend=FakeClosable("graph", calls),
            evidence_index=FakeClosable("evidence", calls),
        )

        await handle.close()

        assert calls == ["evidence", "graph", "postgres"]

    asyncio.run(run())


def test_openclaw_model_clients_use_configured_cli_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_CLI", "pnpm")
    monkeypatch.setenv("OPENCLAW_CLI_ARGS", "openclaw --profile dev")
    monkeypatch.setenv("OPENCLAW_CLI_CWD", "/repo/openclaw")
    resolver = MemWingModelConfigResolver.from_env(
        {
            "MEMWING_MODEL_RUNTIME": "openclaw",
            "MEMWING_MODEL_TRANSPORT": "local",
        }
    )

    llm_client = openclaw_adapter_factory._llm_client_for_role(resolver, "long_term_filter")
    embedding_client = openclaw_adapter_factory._embedding_client_for_role(
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


class FakeConnection:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def close(self) -> None:
        self.calls.append("postgres")
