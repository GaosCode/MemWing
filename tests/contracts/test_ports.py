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
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResult
from memwing.core.models import (
    GraphWriteResult,
    LongTermFilterItem,
    PageMemorySynthesis,
)
from memwing.core.scope import EffectiveScope
from memwing.ports.agent_runtime import AgentRuntimePort
from memwing.ports.clock import ClockPort
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports import event_store
from memwing.ports.audit_events import AuditEventRepositoryPort as SplitAuditEventRepositoryPort
from memwing.ports.control_plane import (
    ForgettingReviewCandidateRepositoryPort as SplitForgettingReviewCandidateRepositoryPort,
    PushCandidateRepositoryPort as SplitPushCandidateRepositoryPort,
)
from memwing.ports.derived_memory import (
    EvidenceChunkRepositoryPort as SplitEvidenceChunkRepositoryPort,
    MemoryItemRepositoryPort as SplitMemoryItemRepositoryPort,
    MemoryPageRepositoryPort as SplitMemoryPageRepositoryPort,
    MemoryPageVersionRepositoryPort as SplitMemoryPageVersionRepositoryPort,
    MemoryRecallEventRepositoryPort as SplitMemoryRecallEventRepositoryPort,
    MemoryVersionRepositoryPort as SplitMemoryVersionRepositoryPort,
    WorkingMemoryRepositoryPort as SplitWorkingMemoryRepositoryPort,
)
from memwing.ports.event_store import (
    AuditEventRepositoryPort,
    EventStorePort,
    EventStoreTransactionPort,
    EvidenceChunkRepositoryPort,
    ForgettingReviewCandidateRepositoryPort,
    GraphWriteJobRepositoryPort,
    OutboxJobRepositoryPort,
    PushCandidateRepositoryPort,
    SourceEventRepositoryPort,
    MemoryGraphLinkRepositoryPort,
    MemoryItemRepositoryPort,
    MemoryPageRepositoryPort,
    MemoryPageVersionRepositoryPort,
    MemoryRecallEventRepositoryPort,
    MemoryVersionRepositoryPort,
    WorkingMemoryRepositoryPort,
)
from memwing.ports.graph_jobs import (
    GraphWriteJobRepositoryPort as SplitGraphWriteJobRepositoryPort,
    MemoryGraphLinkRepositoryPort as SplitMemoryGraphLinkRepositoryPort,
)
from memwing.ports.outbox_jobs import OutboxJobRepositoryPort as SplitOutboxJobRepositoryPort
from memwing.ports.scope_bindings import ScopeBindingStorePort
from memwing.ports.source_events import SourceEventRepositoryPort as SplitSourceEventRepositoryPort
from memwing.ports.graph_backend import (
    GraphBackendPort,
    GraphFactPreseedRequest,
    GraphFactPreseedResult,
    GraphWriteBatchItemResult,
    GraphWriteBatchRequest,
    GraphWriteBatchResult,
    GraphWriteRequest,
)
from memwing.ports.lifecycle_transition import (
    LifecycleTransitionPort,
    LifecycleTransitionRequest,
    LifecycleTransitionResult,
)
from memwing.ports.llm_filter import LongTermFilterPort, LongTermFilterRequest
from memwing.ports.page_memory_synthesis import (
    PageMemorySynthesisPort,
    PageMemorySynthesisRequest,
)
from memwing.ports.platform_connector import PlatformConnectorPort


def test_lane_zero_ports_are_runtime_checkable_contracts() -> None:
    for port in (
        AgentRuntimePort,
        ClockPort,
        EvidenceIndexPort,
        EventStorePort,
        GraphBackendPort,
        LifecycleTransitionPort,
        LongTermFilterPort,
        PageMemorySynthesisPort,
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
        async def search_current(self, query: MemorySearchQuery) -> MemorySearchResult:
            raise NotImplementedError

        async def search_history(self, query: MemorySearchQuery) -> MemorySearchResult:
            raise NotImplementedError

        async def ingest_graph_job(self, request: GraphWriteRequest) -> GraphWriteResult:
            raise NotImplementedError

        async def ingest_graph_jobs(
            self,
            request: GraphWriteBatchRequest,
        ) -> GraphWriteBatchResult:
            raise NotImplementedError

        async def preseed_facts(self, request: GraphFactPreseedRequest) -> GraphFactPreseedResult:
            raise NotImplementedError

        async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
            raise NotImplementedError

    assert isinstance(FakeGraphBackend(), GraphBackendPort)


def test_graph_backend_port_search_uses_internal_memory_search_contract() -> None:
    for method_name in ("search_current", "search_history"):
        signature = inspect.signature(getattr(GraphBackendPort, method_name))
        parameters = list(signature.parameters.values())
        hints = get_type_hints(getattr(GraphBackendPort, method_name))

        assert hints[parameters[1].name] is MemorySearchQuery
        assert hints["return"] is MemorySearchResult


def test_graph_backend_port_exposes_batch_ingest_contract() -> None:
    signature = inspect.signature(getattr(GraphBackendPort, "ingest_graph_jobs"))
    parameters = list(signature.parameters.values())
    hints = get_type_hints(getattr(GraphBackendPort, "ingest_graph_jobs"))

    assert hints[parameters[1].name] is GraphWriteBatchRequest
    assert hints["return"] is GraphWriteBatchResult

    item_hints = get_type_hints(GraphWriteBatchItemResult)
    assert item_hints["error_type"] == str | None
    assert item_hints["retryable"] is bool


def test_graph_backend_port_exposes_direct_fact_preseed_contract() -> None:
    signature = inspect.signature(getattr(GraphBackendPort, "preseed_facts"))
    parameters = list(signature.parameters.values())
    hints = get_type_hints(getattr(GraphBackendPort, "preseed_facts"))

    assert hints[parameters[1].name] is GraphFactPreseedRequest
    assert hints["return"] is GraphFactPreseedResult


def test_graph_backend_port_uses_graph_write_request_contract() -> None:
    signature = inspect.signature(GraphBackendPort.ingest_graph_job)
    parameters = list(signature.parameters.values())
    hints = get_type_hints(GraphBackendPort.ingest_graph_job)

    assert hints[parameters[1].name] is GraphWriteRequest
    assert hints["return"] is GraphWriteResult
    assert not hasattr(GraphBackendPort, "write_facts")


def test_long_term_filter_port_accepts_enriched_request() -> None:
    signature = inspect.signature(LongTermFilterPort.filter_events)
    parameters = list(signature.parameters.values())
    hints = get_type_hints(LongTermFilterPort.filter_events)

    assert parameters[1].name == "request"
    assert hints[parameters[1].name] is LongTermFilterRequest
    assert hints["return"] == tuple[LongTermFilterItem, ...]


def test_lifecycle_transition_port_is_application_seam() -> None:
    class FakeLifecycleTransition:
        async def transition(
            self,
            request: LifecycleTransitionRequest,
        ) -> LifecycleTransitionResult:
            raise NotImplementedError

    assert isinstance(FakeLifecycleTransition(), LifecycleTransitionPort)

    signature = inspect.signature(LifecycleTransitionPort.transition)
    parameters = list(signature.parameters.values())
    hints = get_type_hints(LifecycleTransitionPort.transition)

    assert hints[parameters[1].name] is LifecycleTransitionRequest
    assert hints["return"] is LifecycleTransitionResult


def test_page_memory_synthesis_port_returns_structured_page_memory() -> None:
    class FakePageMemorySynthesis:
        async def synthesize(
            self,
            request: PageMemorySynthesisRequest,
        ) -> PageMemorySynthesis:
            raise NotImplementedError

    assert isinstance(FakePageMemorySynthesis(), PageMemorySynthesisPort)

    signature = inspect.signature(PageMemorySynthesisPort.synthesize)
    parameters = list(signature.parameters.values())
    hints = get_type_hints(PageMemorySynthesisPort.synthesize)

    assert hints[parameters[1].name] is PageMemorySynthesisRequest
    assert hints["return"] is PageMemorySynthesis


def test_event_store_transaction_exposes_d_e_f_repository_boundaries() -> None:
    hints = get_type_hints(EventStoreTransactionPort)

    assert hints["source_events"] is SourceEventRepositoryPort
    assert hints["evidence_chunks"] is EvidenceChunkRepositoryPort
    assert hints["working_memory_entries"] is WorkingMemoryRepositoryPort
    assert hints["memory_recall_events"] is MemoryRecallEventRepositoryPort
    assert hints["memory_items"] is MemoryItemRepositoryPort
    assert hints["memory_versions"] is MemoryVersionRepositoryPort
    assert hints["memory_pages"] is MemoryPageRepositoryPort
    assert hints["memory_page_versions"] is MemoryPageVersionRepositoryPort
    assert hints["graph_write_jobs"] is GraphWriteJobRepositoryPort
    assert hints["memory_graph_links"] is MemoryGraphLinkRepositoryPort
    assert hints["forgetting_review_candidates"] is ForgettingReviewCandidateRepositoryPort
    assert hints["push_candidates"] is PushCandidateRepositoryPort

    assert hasattr(SourceEventRepositoryPort, "list_for_scope")
    assert hasattr(SourceEventRepositoryPort, "list_recent_for_scope")
    assert hasattr(AuditEventRepositoryPort, "list_for_entity")
    assert hasattr(AuditEventRepositoryPort, "get_by_idempotency_key")
    assert hasattr(OutboxJobRepositoryPort, "list_for_project")
    assert hasattr(OutboxJobRepositoryPort, "list_for_source_events")
    assert hasattr(OutboxJobRepositoryPort, "list_for_project_type_and_aggregates")
    assert hasattr(OutboxJobRepositoryPort, "claim_pending_for_types")
    assert hasattr(EvidenceChunkRepositoryPort, "count_by_source_events")
    assert hasattr(WorkingMemoryRepositoryPort, "next_sequence")
    assert hasattr(WorkingMemoryRepositoryPort, "sum_unflushed_tokens")
    assert hasattr(WorkingMemoryRepositoryPort, "count_by_source_events")
    assert hasattr(MemoryItemRepositoryPort, "list_for_scope")
    assert hasattr(MemoryItemRepositoryPort, "list_decay_candidates")
    assert hasattr(MemoryItemRepositoryPort, "get_for_update")
    assert hasattr(MemoryVersionRepositoryPort, "get_latest")
    assert hasattr(MemoryPageRepositoryPort, "lock_scope")
    assert hasattr(MemoryPageRepositoryPort, "list_needs_rebuild")
    assert hasattr(MemoryPageRepositoryPort, "get_by_scope_for_update")
    assert hasattr(hints["memory_recall_events"], "record")
    assert hasattr(GraphWriteJobRepositoryPort, "extend_lock")
    assert hasattr(GraphWriteJobRepositoryPort, "mark_dead_letter")
    assert hasattr(GraphWriteJobRepositoryPort, "list_for_project")
    assert hasattr(GraphWriteJobRepositoryPort, "list_for_source_events")
    assert hasattr(PushCandidateRepositoryPort, "list_for_project")
    assert hasattr(PushCandidateRepositoryPort, "list_pending")


def test_event_store_reexports_split_repository_ports_for_compatibility() -> None:
    assert event_store.SourceEventRepositoryPort is SplitSourceEventRepositoryPort
    assert event_store.AuditEventRepositoryPort is SplitAuditEventRepositoryPort
    assert event_store.OutboxJobRepositoryPort is SplitOutboxJobRepositoryPort
    assert event_store.EvidenceChunkRepositoryPort is SplitEvidenceChunkRepositoryPort
    assert event_store.WorkingMemoryRepositoryPort is SplitWorkingMemoryRepositoryPort
    assert event_store.MemoryRecallEventRepositoryPort is SplitMemoryRecallEventRepositoryPort
    assert event_store.MemoryItemRepositoryPort is SplitMemoryItemRepositoryPort
    assert event_store.MemoryVersionRepositoryPort is SplitMemoryVersionRepositoryPort
    assert event_store.MemoryPageRepositoryPort is SplitMemoryPageRepositoryPort
    assert event_store.MemoryPageVersionRepositoryPort is SplitMemoryPageVersionRepositoryPort
    assert event_store.GraphWriteJobRepositoryPort is SplitGraphWriteJobRepositoryPort
    assert event_store.MemoryGraphLinkRepositoryPort is SplitMemoryGraphLinkRepositoryPort
    assert (
        event_store.ForgettingReviewCandidateRepositoryPort
        is SplitForgettingReviewCandidateRepositoryPort
    )
    assert event_store.PushCandidateRepositoryPort is SplitPushCandidateRepositoryPort
    assert event_store.ScopeBindingStorePort is ScopeBindingStorePort


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
        LifecycleTransitionPort,
        LongTermFilterPort,
        PageMemorySynthesisPort,
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
