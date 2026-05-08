import asyncio

from memwing.infrastructure.agents.openclaw_adapter_factory import (
    OpenClawRuntimeHandle,
    create_openclaw_adapter_from_store,
)
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.runtime_backends import RuntimeBackendsHandle


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


def test_factory_adds_push_trigger_jobs_only_when_auto_push_is_enabled() -> None:
    disabled = create_openclaw_adapter_from_store(InMemoryDataStore())
    enabled = create_openclaw_adapter_from_store(
        InMemoryDataStore(),
        auto_push_enabled=True,
    )

    assert "push_candidate.trigger" not in disabled._memory_gateway._outbox_job_types
    assert "push_candidate.trigger" in enabled._memory_gateway._outbox_job_types


def test_runtime_handle_closes_external_clients_before_postgres() -> None:
    async def run() -> None:
        calls: list[str] = []
        handle = OpenClawRuntimeHandle(
            runtime=object(),
            connection=FakeConnection(calls),
            graph_backend=FakeClosable("graph", calls),
            evidence_index=FakeClosable("evidence", calls),
            extra_backends=(
                RuntimeBackendsHandle(
                    graph_backend=FakeClosable("pipeline_graph", calls),
                    evidence_index=FakeClosable("pipeline_evidence", calls),
                ),
            ),
        )

        await handle.close()

        assert calls == [
            "pipeline_evidence",
            "pipeline_graph",
            "evidence",
            "graph",
            "postgres",
        ]

    asyncio.run(run())


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
