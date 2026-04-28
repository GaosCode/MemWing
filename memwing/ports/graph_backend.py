from __future__ import annotations

from typing import Protocol, runtime_checkable

from memwing.api.agent_runtime import AgentMemoryQuery, AgentMemorySearchResult
from memwing.core.models import GraphWriteJob, GraphWriteResult
from memwing.core.scope import EffectiveScope


@runtime_checkable
class GraphBackendPort(Protocol):
    async def search_current(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        ...

    async def search_history(self, query: AgentMemoryQuery) -> AgentMemorySearchResult:
        ...

    async def ingest_graph_job(self, job: GraphWriteJob) -> GraphWriteResult:
        ...

    async def mark_source_redacted(self, source_event_id: str, scope: EffectiveScope) -> None:
        ...
