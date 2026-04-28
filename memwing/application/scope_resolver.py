from __future__ import annotations

from dataclasses import dataclass

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.platform import PlatformRef
from memwing.core.scope import EffectiveScope, MemoryScope
from memwing.ports.event_store import ScopeBindingStorePort


class ScopeResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    effective_scope: EffectiveScope
    source_group_id: str | None
    thread_id: str | None
    shared_group_id: str | None


class ScopeResolver:
    def __init__(self, bindings: ScopeBindingStorePort) -> None:
        self._bindings = bindings

    async def resolve_runtime(
        self,
        runtime_ref: AgentRuntimeRef,
        scope_hint: MemoryScope,
    ) -> ResolvedScope:
        binding = await self._bindings.find_runtime_scope_binding(
            runtime=runtime_ref.runtime,
            agent_id=runtime_ref.agent_id,
            workspace_id=runtime_ref.workspace_id,
            session_id=runtime_ref.session_id,
        )
        if binding is None:
            raise ScopeResolutionError("runtime scope binding was not found")

        self._require_project_match(scope_hint, binding.project_memory_space_id)
        return await self._build_resolved_scope(
            project_memory_space_id=binding.project_memory_space_id,
            bound_group_id=None,
            bound_thread_id=None,
            hint=scope_hint,
        )

    async def resolve_platform(
        self,
        platform_ref: PlatformRef,
        scope_hint: MemoryScope,
    ) -> ResolvedScope:
        binding = await self._bindings.find_platform_scope_binding(
            platform=platform_ref.platform,
            tenant_id=platform_ref.tenant_id,
            channel_id=platform_ref.channel_id,
            thread_id=platform_ref.thread_id,
        )
        if binding is None:
            raise ScopeResolutionError("platform scope binding was not found")

        self._require_project_match(scope_hint, binding.project_memory_space_id)
        return await self._build_resolved_scope(
            project_memory_space_id=binding.project_memory_space_id,
            bound_group_id=binding.group_id,
            bound_thread_id=binding.thread_id,
            hint=scope_hint,
            platform_thread_id=platform_ref.thread_id,
        )

    async def _build_resolved_scope(
        self,
        *,
        project_memory_space_id: str,
        bound_group_id: str | None,
        bound_thread_id: str | None,
        hint: MemoryScope,
        platform_thread_id: str | None = None,
    ) -> ResolvedScope:
        project = await self._bindings.get_project_memory_space(project_memory_space_id)
        if project is None:
            raise ScopeResolutionError("project memory space was not found")

        source_group_id = self._resolve_group_id(bound_group_id, hint.group_id)
        thread_id = self._resolve_thread_id(bound_thread_id, platform_thread_id, hint.thread_id)
        settings = None
        if source_group_id is not None:
            settings = await self._bindings.get_group_memory_settings(
                project_memory_space_id=project_memory_space_id,
                group_id=source_group_id,
            )

        safe_mode_enabled = (
            settings.safe_mode_enabled
            if settings is not None
            else project.default_safe_mode_enabled
        )
        if safe_mode_enabled and source_group_id is None:
            raise ScopeResolutionError("safe_mode requires group_id")

        shared_group_id = self._resolve_shared_group_id(
            server_shared_group_id=settings.shared_group_id if settings is not None else None,
            hint_shared_group_id=hint.shared_group_id,
        )
        group_ids = (source_group_id,) if safe_mode_enabled and source_group_id is not None else None
        return ResolvedScope(
            effective_scope=EffectiveScope(
                project_memory_space_id=project_memory_space_id,
                group_ids=group_ids,
                thread_id=thread_id,
                shared_group_id=shared_group_id,
                safe_mode_enabled=safe_mode_enabled,
                cross_group_allowed=not safe_mode_enabled,
            ),
            source_group_id=source_group_id,
            thread_id=thread_id,
            shared_group_id=shared_group_id,
        )

    @staticmethod
    def _require_project_match(scope_hint: MemoryScope, bound_project_id: str) -> None:
        if scope_hint.project_memory_space_id != bound_project_id:
            raise ScopeResolutionError("scope_hint project_memory_space_id conflicts with binding")

    @staticmethod
    def _resolve_group_id(bound_group_id: str | None, hint_group_id: str | None) -> str | None:
        if bound_group_id is not None and hint_group_id is not None and bound_group_id != hint_group_id:
            raise ScopeResolutionError("scope_hint group_id conflicts with binding")
        return bound_group_id if bound_group_id is not None else hint_group_id

    @staticmethod
    def _resolve_thread_id(
        bound_thread_id: str | None,
        platform_thread_id: str | None,
        hint_thread_id: str | None,
    ) -> str | None:
        candidates = [value for value in (bound_thread_id, platform_thread_id) if value is not None]
        if hint_thread_id is not None:
            if candidates and hint_thread_id not in candidates:
                raise ScopeResolutionError("scope_hint thread_id conflicts with binding")
            candidates.append(hint_thread_id)
        return candidates[0] if candidates else None

    @staticmethod
    def _resolve_shared_group_id(
        *,
        server_shared_group_id: str | None,
        hint_shared_group_id: str | None,
    ) -> str | None:
        if (
            server_shared_group_id is not None
            and hint_shared_group_id is not None
            and server_shared_group_id != hint_shared_group_id
        ):
            raise ScopeResolutionError("scope_hint shared_group_id conflicts with settings")
        return server_shared_group_id
