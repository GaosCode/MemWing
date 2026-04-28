import asyncio
import fnmatch

import pytest

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.platform import PlatformRef
from memwing.application.scope_resolver import ScopeResolutionError, ScopeResolver
from memwing.core.scope import (
    GroupMemorySettings,
    MemoryScope,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)


class ScopeBindingFixture:
    def __init__(self) -> None:
        self.projects: dict[str, ProjectMemorySpace] = {}
        self.runtime_bindings: list[RuntimeScopeBinding] = []
        self.platform_bindings: list[PlatformScopeBinding] = []
        self.group_settings: dict[tuple[str, str], GroupMemorySettings] = {}

    def add_project_memory_space(self, space: ProjectMemorySpace) -> None:
        self.projects[space.id] = space

    def add_runtime_scope_binding(self, binding: RuntimeScopeBinding) -> None:
        self.runtime_bindings.append(binding)

    def add_platform_scope_binding(self, binding: PlatformScopeBinding) -> None:
        self.platform_bindings.append(binding)

    def add_group_memory_settings(self, settings: GroupMemorySettings) -> None:
        self.group_settings[(settings.project_memory_space_id, settings.group_id)] = settings

    async def get_project_memory_space(
        self, project_memory_space_id: str
    ) -> ProjectMemorySpace | None:
        return self.projects.get(project_memory_space_id)

    async def find_runtime_scope_binding(
        self,
        *,
        runtime: str,
        agent_id: str,
        workspace_id: str | None,
        session_id: str | None,
    ) -> RuntimeScopeBinding | None:
        session_key = session_id or ""
        matches = [
            binding
            for binding in self.runtime_bindings
            if binding.runtime == runtime
            and binding.agent_id == agent_id
            and binding.workspace_id == workspace_id
            and fnmatch.fnmatchcase(session_key, binding.session_key_pattern)
        ]
        return matches[0] if matches else None

    async def find_platform_scope_binding(
        self,
        *,
        platform: str,
        tenant_id: str | None,
        channel_id: str,
        thread_id: str | None,
    ) -> PlatformScopeBinding | None:
        for binding in self.platform_bindings:
            if (
                binding.platform == platform
                and binding.tenant_id == tenant_id
                and binding.channel_id == channel_id
                and binding.thread_id in (thread_id, None)
            ):
                return binding
        return None

    async def get_group_memory_settings(
        self,
        *,
        project_memory_space_id: str,
        group_id: str,
    ) -> GroupMemorySettings | None:
        return self.group_settings.get((project_memory_space_id, group_id))


def test_runtime_scope_uses_binding_as_authority() -> None:
    store = ScopeBindingFixture()
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
            session_key_pattern="session_*",
            project_memory_space_id="project_001",
        )
    )
    resolver = ScopeResolver(store)

    resolved = asyncio.run(
        resolver.resolve_runtime(
            AgentRuntimeRef(
                runtime="openclaw",
                agent_id="agent_001",
                workspace_id="workspace_001",
                session_id="session_123",
            ),
            MemoryScope(
                project_memory_space_id="project_001",
                group_id="group_001",
                thread_id="thread_001",
            ),
        )
    )

    assert resolved.effective_scope.project_memory_space_id == "project_001"
    assert resolved.effective_scope.safe_mode_enabled is False
    assert resolved.effective_scope.group_ids is None
    assert resolved.effective_scope.cross_group_allowed is True
    assert resolved.source_group_id == "group_001"
    assert resolved.thread_id == "thread_001"


def test_scope_hint_cannot_override_bound_project_or_group() -> None:
    store = ScopeBindingFixture()
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
            group_id="group_001",
        )
    )
    resolver = ScopeResolver(store)

    with pytest.raises(ScopeResolutionError, match="project_memory_space_id"):
        asyncio.run(
            resolver.resolve_platform(
                PlatformRef(
                    platform="feishu",
                    tenant_id="tenant_001",
                    channel_id="chat_001",
                    thread_id=None,
                    message_id="message_001",
                ),
                MemoryScope(
                    project_memory_space_id="project_other",
                    group_id="group_001",
                ),
            )
        )

    with pytest.raises(ScopeResolutionError, match="group_id"):
        asyncio.run(
            resolver.resolve_platform(
                PlatformRef(
                    platform="feishu",
                    tenant_id="tenant_001",
                    channel_id="chat_001",
                    thread_id=None,
                    message_id="message_001",
                ),
                MemoryScope(
                    project_memory_space_id="project_001",
                    group_id="group_other",
                ),
            )
        )


def test_safe_mode_requires_group_and_uses_shared_group_setting() -> None:
    store = ScopeBindingFixture()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Safe Demo",
            default_safe_mode_enabled=True,
        )
    )
    store.add_platform_scope_binding(
        PlatformScopeBinding(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id=None,
            project_memory_space_id="project_001",
            group_id="group_001",
        )
    )
    store.add_group_memory_settings(
        GroupMemorySettings(
            project_memory_space_id="project_001",
            group_id="group_001",
            safe_mode_enabled=True,
            shared_group_id="shared_001",
        )
    )
    resolver = ScopeResolver(store)

    resolved = asyncio.run(
        resolver.resolve_platform(
            PlatformRef(
                platform="feishu",
                tenant_id="tenant_001",
                channel_id="chat_001",
                thread_id=None,
                message_id="message_001",
            ),
            MemoryScope(
                project_memory_space_id="project_001",
                group_id="group_001",
            ),
        )
    )

    assert resolved.effective_scope.safe_mode_enabled is True
    assert resolved.effective_scope.group_ids == ("group_001",)
    assert resolved.effective_scope.cross_group_allowed is False
    assert resolved.effective_scope.shared_group_id == "shared_001"
    assert resolved.shared_group_id == "shared_001"


def test_safe_mode_does_not_accept_client_shared_group_hint() -> None:
    store = ScopeBindingFixture()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Safe Demo",
            default_safe_mode_enabled=True,
        )
    )
    store.add_platform_scope_binding(
        PlatformScopeBinding(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="chat_001",
            thread_id=None,
            project_memory_space_id="project_001",
            group_id="group_001",
        )
    )
    store.add_group_memory_settings(
        GroupMemorySettings(
            project_memory_space_id="project_001",
            group_id="group_001",
            safe_mode_enabled=True,
            shared_group_id=None,
        )
    )
    resolver = ScopeResolver(store)

    resolved = asyncio.run(
        resolver.resolve_platform(
            PlatformRef(
                platform="feishu",
                tenant_id="tenant_001",
                channel_id="chat_001",
                thread_id=None,
                message_id="message_001",
            ),
            MemoryScope(
                project_memory_space_id="project_001",
                group_id="group_001",
                shared_group_id="client_shared",
            ),
        )
    )

    assert resolved.effective_scope.safe_mode_enabled is True
    assert resolved.effective_scope.group_ids == ("group_001",)
    assert resolved.effective_scope.shared_group_id is None
    assert resolved.effective_scope.cross_group_allowed is False
    assert resolved.shared_group_id is None


def test_missing_binding_fails_explicitly() -> None:
    resolver = ScopeResolver(ScopeBindingFixture())

    with pytest.raises(ScopeResolutionError, match="runtime scope binding"):
        asyncio.run(
            resolver.resolve_runtime(
                AgentRuntimeRef(
                    runtime="openclaw",
                    agent_id="agent_missing",
                    workspace_id="workspace_001",
                    session_id="session_001",
                ),
                MemoryScope(project_memory_space_id="project_001"),
            )
        )
