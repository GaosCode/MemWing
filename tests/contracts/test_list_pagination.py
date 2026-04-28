import inspect

import pytest

from memwing.api.schemas import (
    AgentMemoryQuery,
    AgentRuntimeRef,
    OpenClawNativeMemorySearchRequest,
    SchemaValidationError,
)
from memwing.core.scope import MemoryScope


def test_agent_memory_query_uses_limit_cursor_sort_without_max_results() -> None:
    parameters = inspect.signature(AgentMemoryQuery).parameters

    assert "runtime_ref" in parameters
    assert "mode" in parameters
    assert "limit" in parameters
    assert "cursor" in parameters
    assert "sort" in parameters
    assert "min_score" in parameters
    assert "scope" in parameters
    assert "max_results" not in parameters

    runtime_ref = AgentRuntimeRef(runtime="openclaw", agent_id="agent_001")
    scope = MemoryScope(project_memory_space_id="project_001", group_id="group_001")
    query = AgentMemoryQuery(
        runtime_ref=runtime_ref,
        query="demo scope",
        mode="history",
        limit=10,
        cursor="next",
        sort="event_time",
        min_score=0.25,
        scope=scope,
    )

    assert query.runtime_ref is runtime_ref
    assert query.mode == "history"
    assert query.limit == 10
    assert query.cursor == "next"
    assert query.sort == "event_time"
    assert query.min_score == 0.25
    assert query.scope is scope

    with pytest.raises(TypeError):
        AgentMemoryQuery(  # type: ignore[call-arg]
            runtime_ref=runtime_ref,
            query="demo scope",
            max_results=10,
            scope=scope,
        )


def test_openclaw_native_memory_request_translates_max_results_to_limit() -> None:
    runtime_ref = AgentRuntimeRef(
        runtime="openclaw",
        agent_id="agent_001",
        workspace_id="workspace_001",
        session_id="session_001",
    )
    scope = MemoryScope(project_memory_space_id="project_001", group_id="group_001")
    native_request = OpenClawNativeMemorySearchRequest(
        runtime_ref=runtime_ref,
        query="demo scope",
        max_results=7,
        scope=scope,
    )

    agent_query = native_request.to_agent_memory_query()

    assert agent_query.runtime_ref is runtime_ref
    assert agent_query.query == "demo scope"
    assert agent_query.mode == "current"
    assert agent_query.limit == 7
    assert agent_query.cursor is None
    assert agent_query.sort == "relevance"
    assert agent_query.min_score == 0
    assert agent_query.scope is scope


def test_openclaw_native_memory_request_preserves_search_contract_fields() -> None:
    runtime_ref = AgentRuntimeRef(
        runtime="openclaw",
        agent_id="agent_001",
        workspace_id="workspace_001",
        session_id="session_001",
    )
    scope = MemoryScope(project_memory_space_id="project_001", group_id="group_001")
    native_request = OpenClawNativeMemorySearchRequest(
        runtime_ref=runtime_ref,
        query="demo scope",
        max_results=7,
        mode="history",
        min_score=0.25,
        scope=scope,
    )

    agent_query = native_request.to_agent_memory_query()

    assert agent_query.mode == "history"
    assert agent_query.min_score == 0.25
    assert agent_query.limit == 7


def test_openclaw_native_memory_request_rejects_invalid_search_contract_fields() -> None:
    runtime_ref = AgentRuntimeRef(runtime="openclaw", agent_id="agent_001")
    scope = MemoryScope(project_memory_space_id="project_001", group_id="group_001")

    with pytest.raises(SchemaValidationError, match="mode"):
        OpenClawNativeMemorySearchRequest(
            runtime_ref=runtime_ref,
            query="demo scope",
            max_results=7,
            mode="all",  # type: ignore[arg-type]
            scope=scope,
        )

    with pytest.raises(SchemaValidationError, match="min_score"):
        OpenClawNativeMemorySearchRequest(
            runtime_ref=runtime_ref,
            query="demo scope",
            max_results=7,
            min_score=-0.1,
            scope=scope,
        )
