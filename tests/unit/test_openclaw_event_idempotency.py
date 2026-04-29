import asyncio
from datetime import UTC, datetime

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.agent_context import AgentRuntimeEvent
from memwing.application.gateway_service import MemoryGateway
from memwing.application.remember_event_command import agent_runtime_event_to_remember_command
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.scope import MemoryScope, ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.in_memory import InMemoryDataStore


def test_agent_runtime_event_idempotency_key_prevents_duplicate_source_events() -> None:
    store = InMemoryDataStore()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Demo",
            default_safe_mode_enabled=False,
        )
    )
    store.add_runtime_scope_binding(
        RuntimeScopeBinding(
            runtime="openclaw",
            agent_id="agent_001",
            workspace_id="workspace_001",
            session_key_pattern="session_001",
            project_memory_space_id="project_001",
        )
    )
    gateway = MemoryGateway(store, ScopeResolver(store))
    event = AgentRuntimeEvent(
        runtime_ref=AgentRuntimeRef(
            runtime="openclaw",
            agent_id="agent_001",
            workspace_id="workspace_001",
            session_id="session_001",
        ),
        run_id="run_001",
        message_id="message_001",
        tool_call_id=None,
        hook_name="afterTurn",
        sequence=1,
        idempotency_key="openclaw:agent_001:session_001:run_001:afterTurn",
        event_type="turn_completed",
        scope=MemoryScope(project_memory_space_id="project_001", group_id="group_001"),
        content="Keep Data Foundation backend-only.",
        payload={"decision": "backend-only"},
        event_time=datetime(2026, 4, 28, tzinfo=UTC),
    )

    command = agent_runtime_event_to_remember_command(event)
    first = asyncio.run(gateway.remember_event(command))
    second = asyncio.run(gateway.remember_event(command))

    assert first.accepted is True
    assert second.accepted is True
    assert second.source_event_id == first.source_event_id
    assert second.duplicate_of == first.source_event_id
    assert len(store.source_events) == 1
    assert len(store.outbox_jobs) == 4
    assert store.source_events[0].runtime_event_idempotency_key == event.idempotency_key
