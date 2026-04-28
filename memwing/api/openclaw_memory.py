from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from memwing.api.agent_knowledge import AgentRuntimeStatusRequest
from memwing.api.agent_memory import AgentMemoryResultItem, OpenClawNativeMemorySearchRequest
from memwing.api.memwing_tools import memwing_get_memory
from memwing.api.types import JsonObject
from memwing.api.validation import SchemaValidationError, require_text
from memwing.core.scope import MemoryScope
from memwing.infrastructure.agents.openclaw_adapter import OpenClawAdapter
from memwing.infrastructure.agents.openclaw_event_mapper import (
    memory_scope_from_payload,
    openclaw_runtime_ref_from_payload,
)
from memwing.ports.agent_runtime import AgentRuntimePort


@dataclass(frozen=True, slots=True)
class OpenClawNativeMemoryIndexResult:
    accepted: bool
    indexed: bool
    force: bool
    trace_id: str


@dataclass(frozen=True, slots=True)
class OpenClawNativeMemoryStatusEnvelope:
    agent_id: str
    project_memory_space_id: str
    workspace_id: str | None
    safe_mode: bool
    evidence_index_status: str
    graph_backend_status: str
    pending_graph_jobs: int
    pending_page_jobs: int
    last_error: str | None
    capabilities: tuple[str, ...]
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_id", require_text(self.agent_id, "agent_id"))
        object.__setattr__(
            self,
            "project_memory_space_id",
            require_text(self.project_memory_space_id, "project_memory_space_id"),
        )
        if self.workspace_id is not None:
            object.__setattr__(self, "workspace_id", require_text(self.workspace_id, "workspace_id"))
        object.__setattr__(
            self,
            "evidence_index_status",
            require_text(self.evidence_index_status, "evidence_index_status"),
        )
        object.__setattr__(
            self,
            "graph_backend_status",
            require_text(self.graph_backend_status, "graph_backend_status"),
        )
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


async def native_memory_search(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
) -> JsonObject:
    request = OpenClawNativeMemorySearchRequest(
        runtime_ref=openclaw_runtime_ref_from_payload(payload),
        query=_required_text(payload.get("query"), "query"),
        scope=memory_scope_from_payload(payload),
        max_results=_max_results(payload.get("max_results")),
    )
    result = await _runtime(runtime).knowledge_search(request.to_agent_memory_query())
    return {
        "contexts": result.contexts,
        "results": tuple(_result_item_to_json(item) for item in result.results),
        "next_cursor": result.next_cursor,
        "trace_id": result.trace_id,
    }


async def native_memory_get(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
) -> object:
    return await memwing_get_memory(payload, runtime)


async def native_memory_index(payload: Mapping[str, object]) -> OpenClawNativeMemoryIndexResult:
    return OpenClawNativeMemoryIndexResult(
        accepted=True,
        indexed=False,
        force=_force(payload.get("force")),
        trace_id="openclaw_native_index:mock",
    )


async def native_memory_status(
    payload: Mapping[str, object],
    runtime: AgentRuntimePort | None = None,
) -> OpenClawNativeMemoryStatusEnvelope:
    runtime_ref = openclaw_runtime_ref_from_payload(payload)
    scope = _scope_from_status_payload(payload)
    status = await _runtime(runtime).runtime_status(AgentRuntimeStatusRequest(runtime_ref))
    return OpenClawNativeMemoryStatusEnvelope(
        agent_id=runtime_ref.agent_id,
        project_memory_space_id=scope.project_memory_space_id,
        workspace_id=runtime_ref.workspace_id,
        safe_mode=False,
        evidence_index_status="mock_not_connected",
        graph_backend_status="mock_not_connected",
        pending_graph_jobs=0,
        pending_page_jobs=0,
        last_error=None,
        capabilities=status.capabilities,
        trace_id=status.trace_id,
    )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} is required")
    return require_text(value, field_name)


def _max_results(value: object) -> int:
    if value is None:
        return 20
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SchemaValidationError("max_results must be a positive integer")
    return value


def _force(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise SchemaValidationError("force must be a boolean")
    return value


def _result_item_to_json(item: AgentMemoryResultItem) -> JsonObject:
    return {
        "id": item.id,
        "text": item.text,
        "score": item.score,
        "source": item.source,
        "source_event_ids": item.source_event_ids,
        "memory_item_ids": item.memory_item_ids,
        "valid_from": item.valid_from.isoformat() if item.valid_from else None,
        "valid_to": item.valid_to.isoformat() if item.valid_to else None,
        "metadata": item.metadata,
    }


def _scope_from_status_payload(payload: Mapping[str, object]) -> MemoryScope:
    if "scope" in payload:
        return memory_scope_from_payload(payload)
    return MemoryScope(
        project_memory_space_id=_required_text(
            payload.get("project_memory_space_id"),
            "project_memory_space_id",
        ),
        group_id=None,
        thread_id=None,
        shared_group_id=None,
    )


def _runtime(runtime: AgentRuntimePort | None) -> AgentRuntimePort:
    return runtime if runtime is not None else OpenClawAdapter()
