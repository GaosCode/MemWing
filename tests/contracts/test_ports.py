import inspect
from typing import get_type_hints

from memwing.api.schemas import (
    AgentContextRequest,
    AgentContextResult,
    AgentKnowledgeExplainRequest,
    AgentKnowledgeExplainResult,
    AgentKnowledgeGetRequest,
    AgentKnowledgeGetResult,
    AgentMemoryQuery,
    AgentMemorySearchResult,
    AgentRuntimeEvent,
    AgentRuntimeStatusRequest,
    AgentRuntimeStatusResult,
    PlatformRawEvent,
    PlatformRawRequest,
    PlatformSendResult,
    PushCandidate,
    RememberEventResult,
)
from memwing.core.models import GraphWriteJob, GraphWriteResult
from memwing.core.scope import EffectiveScope
from memwing.ports.agent_runtime import AgentRuntimePort
from memwing.ports.clock import ClockPort
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStorePort
from memwing.ports.graph_backend import GraphBackendPort
from memwing.ports.llm_filter import LongTermFilterPort
from memwing.ports.platform_connector import PlatformConnectorPort


def test_lane_zero_ports_are_runtime_checkable_contracts() -> None:
    for port in (
        AgentRuntimePort,
        ClockPort,
        EvidenceIndexPort,
        EventStorePort,
        GraphBackendPort,
        LongTermFilterPort,
        PlatformConnectorPort,
    ):
        assert getattr(port, "_is_runtime_protocol") is True


def test_agent_runtime_port_accepts_adapter_with_required_methods() -> None:
    class FakeAgentRuntime:
        async def build_context(self, request: AgentContextRequest) -> AgentContextResult:
            raise NotImplementedError

        async def remember_runtime_event(self, event: AgentRuntimeEvent) -> RememberEventResult:
            raise NotImplementedError

        async def knowledge_search(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
            raise NotImplementedError

        async def knowledge_get(
            self, request: AgentKnowledgeGetRequest
        ) -> AgentKnowledgeGetResult:
            raise NotImplementedError

        async def knowledge_explain(
            self, request: AgentKnowledgeExplainRequest
        ) -> AgentKnowledgeExplainResult:
            raise NotImplementedError

        async def runtime_status(
            self, request: AgentRuntimeStatusRequest
        ) -> AgentRuntimeStatusResult:
            raise NotImplementedError

    assert isinstance(FakeAgentRuntime(), AgentRuntimePort)


def test_agent_runtime_port_method_names_and_types_are_frozen() -> None:
    expected = {
        "build_context": (AgentContextRequest, AgentContextResult),
        "remember_runtime_event": (AgentRuntimeEvent, RememberEventResult),
        "knowledge_search": (AgentMemoryQuery, AgentMemorySearchResult),
        "knowledge_get": (AgentKnowledgeGetRequest, AgentKnowledgeGetResult),
        "knowledge_explain": (AgentKnowledgeExplainRequest, AgentKnowledgeExplainResult),
        "runtime_status": (AgentRuntimeStatusRequest, AgentRuntimeStatusResult),
    }

    for method_name, (request_type, result_type) in expected.items():
        signature = inspect.signature(getattr(AgentRuntimePort, method_name))
        parameters = list(signature.parameters.values())
        hints = get_type_hints(getattr(AgentRuntimePort, method_name))

        assert hints[parameters[1].name] is request_type
        assert hints["return"] is result_type

    assert not hasattr(AgentRuntimePort, "ingest_event")
    assert not hasattr(AgentRuntimePort, "assemble_context")


def test_graph_backend_port_accepts_adapter_with_required_methods() -> None:
    class FakeGraphBackend:
        async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
            raise NotImplementedError

        async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
            raise NotImplementedError

        async def ingest_graph_job(self, job: GraphWriteJob) -> GraphWriteResult:
            raise NotImplementedError

        async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
            raise NotImplementedError

    assert isinstance(FakeGraphBackend(), GraphBackendPort)


def test_graph_backend_port_uses_graph_write_job_contract() -> None:
    signature = inspect.signature(GraphBackendPort.ingest_graph_job)
    parameters = list(signature.parameters.values())
    hints = get_type_hints(GraphBackendPort.ingest_graph_job)

    assert hints[parameters[1].name] is GraphWriteJob
    assert hints["return"] is GraphWriteResult
    assert not hasattr(GraphBackendPort, "write_facts")


def test_platform_connector_port_freezes_feishu_boundary_methods() -> None:
    class FakePlatformConnector:
        async def verify_request(self, raw_request: PlatformRawRequest) -> bool:
            raise NotImplementedError

        async def normalize_event(self, raw_event: PlatformRawEvent):
            raise NotImplementedError

        async def send_candidate(self, candidate: PushCandidate) -> PlatformSendResult:
            raise NotImplementedError

    assert isinstance(FakePlatformConnector(), PlatformConnectorPort)

    expected = {
        "verify_request": (PlatformRawRequest, bool),
        "normalize_event": (PlatformRawEvent, "PlatformEvent"),
        "send_candidate": (PushCandidate, PlatformSendResult),
    }
    for method_name, (request_type, result_type) in expected.items():
        signature = inspect.signature(getattr(PlatformConnectorPort, method_name))
        parameters = list(signature.parameters.values())
        hints = get_type_hints(getattr(PlatformConnectorPort, method_name))

        assert hints[parameters[1].name] is request_type
        if isinstance(result_type, str):
            assert hints["return"].__name__ == result_type
        else:
            assert hints["return"] is result_type

    assert not hasattr(PlatformConnectorPort, "send_push")


def test_ports_do_not_use_object_placeholders() -> None:
    ports = (
        AgentRuntimePort,
        EvidenceIndexPort,
        EventStorePort,
        GraphBackendPort,
        LongTermFilterPort,
        PlatformConnectorPort,
    )

    for port in ports:
        for name, member in inspect.getmembers(port, inspect.isfunction):
            if name.startswith("_"):
                continue
            signature = inspect.signature(member)
            hints = get_type_hints(member)
            annotations = [
                hints[parameter.name]
                for parameter in signature.parameters.values()
                if parameter.name != "self"
            ]
            annotations.append(hints["return"])

            assert object not in annotations
