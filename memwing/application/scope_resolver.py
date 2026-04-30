from __future__ import annotations

from dataclasses import dataclass

from memwing.api.agent_common import AgentRuntimeRef
from memwing.api.platform import PlatformRef
from memwing.core.models import PageMemory
from memwing.core.scope import EffectiveScope, MemoryScope, PlatformScopeBinding, RuntimeScopeBinding
from memwing.core.scope_patterns import session_pattern_matches, session_pattern_specificity
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
        candidates = await self._bindings.list_runtime_scope_binding_candidates(
            runtime=runtime_ref.runtime,
            agent_id=runtime_ref.agent_id,
            workspace_id=runtime_ref.workspace_id,
            session_id=runtime_ref.session_id,
        )
        binding = self._select_runtime_binding(candidates, runtime_ref.session_id or "")
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
        candidates = await self._bindings.list_platform_scope_binding_candidates(
            platform=platform_ref.platform,
            tenant_id=platform_ref.tenant_id,
            channel_id=platform_ref.channel_id,
            thread_id=platform_ref.thread_id,
        )
        binding = self._select_platform_binding(candidates, platform_ref.thread_id)
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

    async def resolve_page_memory_rebuild(self, page: PageMemory) -> ResolvedScope:
        project = await self._bindings.get_project_memory_space(page.project_memory_space_id)
        if project is None:
            raise ScopeResolutionError("project memory space was not found")

        source_group_id = _page_source_group_id(page)
        thread_id = _page_thread_id(page)
        settings = None
        if source_group_id is not None:
            settings = await self._bindings.get_group_memory_settings(
                project_memory_space_id=page.project_memory_space_id,
                group_id=source_group_id,
            )

        safe_mode_enabled = (
            settings.safe_mode_enabled
            if settings is not None
            else project.default_safe_mode_enabled
        )
        if safe_mode_enabled and source_group_id is None:
            raise ScopeResolutionError("safe_mode requires group_id")

        if page.scope_type == "thread":
            shared_group_id = self._resolve_shared_group_id(
                server_shared_group_id=settings.shared_group_id if settings is not None else None,
                hint_shared_group_id=page.shared_group_id,
            )
        elif page.shared_group_id is not None:
            raise ScopeResolutionError("page scope conflicts with persisted shared group context")
        else:
            shared_group_id = None
        group_ids = (source_group_id,) if source_group_id is not None else None
        return ResolvedScope(
            effective_scope=EffectiveScope(
                project_memory_space_id=page.project_memory_space_id,
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
    def _select_runtime_binding(
        candidates: tuple[RuntimeScopeBinding, ...],
        session_key: str,
    ) -> RuntimeScopeBinding | None:
        matching = [
            candidate
            for candidate in candidates
            if session_pattern_matches(candidate.session_key_pattern, session_key)
        ]
        if not matching:
            return None
        highest_specificity = max(
            session_pattern_specificity(candidate.session_key_pattern)
            for candidate in matching
        )
        winners = [
            candidate
            for candidate in matching
            if session_pattern_specificity(candidate.session_key_pattern) == highest_specificity
        ]
        if len(winners) > 1:
            raise ScopeResolutionError("runtime scope binding conflict")
        return winners[0]

    @staticmethod
    def _select_platform_binding(
        candidates: tuple[PlatformScopeBinding, ...],
        request_thread_id: str | None,
    ) -> PlatformScopeBinding | None:
        eligible = [
            candidate
            for candidate in candidates
            if candidate.thread_id is None
            or (request_thread_id is not None and candidate.thread_id == request_thread_id)
        ]
        if request_thread_id is None:
            eligible = [candidate for candidate in eligible if candidate.thread_id is None]
        if not eligible:
            return None

        thread_specific = [candidate for candidate in eligible if candidate.thread_id is not None]
        winners = thread_specific or [candidate for candidate in eligible if candidate.thread_id is None]
        if len(winners) > 1:
            raise ScopeResolutionError("platform scope binding conflict")
        return winners[0]

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


def _page_source_group_id(page: PageMemory) -> str | None:
    if page.scope_type == "project":
        if (
            page.group_id is not None
            or page.thread_id is not None
            or page.shared_group_id is not None
        ):
            raise ScopeResolutionError("project page scope conflicts with persisted group context")
        return None
    if page.scope_type == "group":
        if page.group_id is None or page.group_id != page.scope_id:
            raise ScopeResolutionError("group page scope conflicts with persisted group context")
        if page.thread_id is not None:
            raise ScopeResolutionError("group page scope conflicts with persisted thread context")
        return page.group_id
    if page.scope_type == "thread":
        if page.thread_id is None or page.thread_id != page.scope_id:
            raise ScopeResolutionError("thread page scope conflicts with persisted thread context")
        return page.group_id
    raise ScopeResolutionError("meeting page memory rebuild is not supported")


def _page_thread_id(page: PageMemory) -> str | None:
    if page.scope_type == "thread":
        return page.thread_id
    return None
