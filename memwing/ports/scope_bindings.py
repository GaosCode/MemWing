from __future__ import annotations

from typing import Protocol

from memwing.core.scope import (
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)


class ScopeBindingStorePort(Protocol):
    async def get_project_memory_space(
        self, project_memory_space_id: str
    ) -> ProjectMemorySpace | None:
        ...

    async def list_runtime_scope_binding_candidates(
        self,
        *,
        runtime: str,
        agent_id: str,
        workspace_id: str | None,
        session_id: str | None,
    ) -> tuple[RuntimeScopeBinding, ...]:
        ...

    async def list_platform_scope_binding_candidates(
        self,
        *,
        platform: str,
        tenant_id: str | None,
        channel_id: str,
        thread_id: str | None,
    ) -> tuple[PlatformScopeBinding, ...]:
        ...

    async def get_group_memory_settings(
        self,
        *,
        project_memory_space_id: str,
        group_id: str,
    ) -> GroupMemorySettings | None:
        ...
