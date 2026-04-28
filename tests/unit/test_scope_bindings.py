import asyncio

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.platform import PlatformRef
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.scope import (
    MemoryScope,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)
from memwing.core.scope_patterns import session_pattern_matches
from memwing.infrastructure.db.in_memory import InMemoryDataStore


def test_platform_thread_binding_wins_over_channel_binding() -> None:
    store = InMemoryDataStore()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Demo",
            default_safe_mode_enabled=False,
        )
    )
    store.add_platform_scope_binding(
        PlatformScopeBinding(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id=None,
            project_memory_space_id="project_001",
            group_id="group_channel",
        )
    )
    store.add_platform_scope_binding(
        PlatformScopeBinding(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id="thread_001",
            project_memory_space_id="project_001",
            group_id="group_thread",
        )
    )

    resolved = asyncio.run(
        ScopeResolver(store).resolve_platform(
            PlatformRef(
                platform="feishu",
                tenant_id="tenant_001",
                channel_id="chat_001",
                thread_id="thread_001",
                message_id="message_001",
            ),
            MemoryScope(
                project_memory_space_id="project_001",
                group_id="group_thread",
            ),
        )
    )

    assert resolved.source_group_id == "group_thread"
    assert resolved.thread_id == "thread_001"


def test_runtime_session_key_pattern_matches_session_id() -> None:
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
            session_key_pattern="feature/*",
            project_memory_space_id="project_001",
        )
    )

    resolved = asyncio.run(
        ScopeResolver(store).resolve_runtime(
            AgentRuntimeRef(
                runtime="openclaw",
                agent_id="agent_001",
                workspace_id="workspace_001",
                session_id="feature/lane-a",
            ),
            MemoryScope(project_memory_space_id="project_001"),
        )
    )

    assert resolved.effective_scope.project_memory_space_id == "project_001"
    assert resolved.source_group_id is None


def test_runtime_session_key_pattern_treats_percent_and_underscore_as_literals() -> None:
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
            session_key_pattern="session_100%_*",
            project_memory_space_id="project_001",
        )
    )

    missing = asyncio.run(
        store.find_runtime_scope_binding(
            runtime="openclaw",
            agent_id="agent_001",
            workspace_id="workspace_001",
            session_id="sessionX100Z_more",
        )
    )
    matched = asyncio.run(
        store.find_runtime_scope_binding(
            runtime="openclaw",
            agent_id="agent_001",
            workspace_id="workspace_001",
            session_id="session_100%_more",
        )
    )

    assert missing is None
    assert matched is not None


def test_runtime_session_key_pattern_treats_only_star_as_wildcard() -> None:
    assert session_pattern_matches("feature/*", "feature/lane-a")
    assert session_pattern_matches("session_100%_*", "session_100%_more")
    assert session_pattern_matches(r"path\\*", r"path\\child")
    assert not session_pattern_matches("session_100%_*", "sessionX100Z_more")
