from __future__ import annotations

import asyncio
import copy

from memwing.core.models import (
    AuditEvent,
    ForgettingReviewCandidate,
    GraphWriteJob,
    MemoryGraphLink,
    MemoryRecallEvent,
    OutboxJob,
    PushCandidate,
    SourceEvent,
)
from memwing.core.scope_patterns import session_pattern_matches
from memwing.core.scope import (
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
    RuntimeScopeBinding,
)

from .in_memory_evidence_repositories import (
    InMemoryEvidenceChunkRepository,
    InMemoryWorkingMemoryRepository,
)
from .in_memory_graph_repositories import (
    InMemoryGraphWriteJobRepository,
    InMemoryMemoryGraphLinkRepository,
)
from .in_memory_memory_repositories import (
    InMemoryForgettingReviewCandidateRepository,
    InMemoryMemoryItemRepository,
    InMemoryMemoryPageRepository,
    InMemoryMemoryPageVersionRepository,
    InMemoryMemoryRecallEventRepository,
    InMemoryMemoryVersionRepository,
)
from .in_memory_model_cache import InMemoryModelResultCacheRepository
from .in_memory_repositories import (
    InMemoryAuditEventRepository,
    InMemoryOutboxJobRepository,
    InMemorySourceEventRepository,
)
from .in_memory_push_repositories import InMemoryPushCandidateRepository
from .in_memory_state import InMemoryState


class InMemoryDataStore:
    def __init__(self, *, fail_on_outbox_job_type: str | None = None) -> None:
        self._state = InMemoryState()
        self._lock = asyncio.Lock()
        self._fail_on_outbox_job_type = fail_on_outbox_job_type

    @property
    def source_events(self) -> tuple[SourceEvent, ...]:
        return tuple(self._state.source_events.values())

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._state.audit_events.values())

    @property
    def outbox_jobs(self) -> tuple[OutboxJob, ...]:
        return tuple(self._state.outbox_jobs.values())

    @property
    def graph_write_jobs(self) -> tuple[GraphWriteJob, ...]:
        return tuple(self._state.graph_write_jobs.values())

    @property
    def memory_graph_links(self) -> tuple[MemoryGraphLink, ...]:
        return tuple(self._state.memory_graph_links.values())

    @property
    def memory_recall_events(self) -> tuple[MemoryRecallEvent, ...]:
        return tuple(self._state.memory_recall_events.values())

    @property
    def forgetting_review_candidates(self) -> tuple[ForgettingReviewCandidate, ...]:
        return tuple(self._state.forgetting_review_candidates.values())

    @property
    def push_candidates(self) -> tuple[PushCandidate, ...]:
        return tuple(self._state.push_candidates.values())

    def add_project_memory_space(self, space: ProjectMemorySpace) -> None:
        self._state.projects[space.id] = space

    def add_runtime_scope_binding(self, binding: RuntimeScopeBinding) -> None:
        self._state.runtime_bindings.append(binding)

    def add_platform_scope_binding(self, binding: PlatformScopeBinding) -> None:
        self._state.platform_bindings.append(binding)

    def add_group_memory_settings(self, settings: GroupMemorySettings) -> None:
        self._state.group_settings[(settings.project_memory_space_id, settings.group_id)] = settings

    def add_outbox_job(self, job: OutboxJob) -> None:
        self._state.outbox_jobs[job.id] = job
        self._state.outbox_by_idempotency_key[job.idempotency_key] = job.id

    def add_graph_write_job(self, job: GraphWriteJob) -> None:
        self._state.graph_write_jobs[job.id] = job
        self._state.graph_job_by_idempotency_key[job.idempotency_key] = job.id

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def get_project_memory_space(
        self,
        project_memory_space_id: str,
    ) -> ProjectMemorySpace | None:
        return self._state.projects.get(project_memory_space_id)

    async def list_runtime_scope_binding_candidates(
        self,
        *,
        runtime: str,
        agent_id: str,
        workspace_id: str | None,
        session_id: str | None,
    ) -> tuple[RuntimeScopeBinding, ...]:
        session_key = session_id or ""
        return tuple(
            binding
            for binding in self._state.runtime_bindings
            if binding.runtime == runtime
            and binding.agent_id == agent_id
            and binding.workspace_id == workspace_id
            and session_pattern_matches(binding.session_key_pattern, session_key)
        )

    async def list_platform_scope_binding_candidates(
        self,
        *,
        platform: str,
        tenant_id: str | None,
        channel_id: str,
        thread_id: str | None,
    ) -> tuple[PlatformScopeBinding, ...]:
        return tuple(
            binding
            for binding in self._state.platform_bindings
            if binding.platform == platform
            and binding.tenant_id == tenant_id
            and binding.channel_id == channel_id
            and binding.thread_id in (thread_id, None)
        )

    async def get_group_memory_settings(
        self,
        *,
        project_memory_space_id: str,
        group_id: str,
    ) -> GroupMemorySettings | None:
        return self._state.group_settings.get((project_memory_space_id, group_id))


class _Transaction:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store
        self._state = InMemoryState()
        self.source_events = InMemorySourceEventRepository(self)
        self.audit_events = InMemoryAuditEventRepository(self)
        self.outbox_jobs = InMemoryOutboxJobRepository(self)
        self.evidence_chunks = InMemoryEvidenceChunkRepository(self)
        self.working_memory_entries = InMemoryWorkingMemoryRepository(self)
        self.memory_recall_events = InMemoryMemoryRecallEventRepository(self)
        self.memory_items = InMemoryMemoryItemRepository(self)
        self.memory_versions = InMemoryMemoryVersionRepository(self)
        self.memory_pages = InMemoryMemoryPageRepository(self)
        self.memory_page_versions = InMemoryMemoryPageVersionRepository(self)
        self.graph_write_jobs = InMemoryGraphWriteJobRepository(self)
        self.memory_graph_links = InMemoryMemoryGraphLinkRepository(self)
        self.forgetting_review_candidates = InMemoryForgettingReviewCandidateRepository(self)
        self.push_candidates = InMemoryPushCandidateRepository(self)
        self.model_result_cache = InMemoryModelResultCacheRepository(self)

    async def __aenter__(self) -> _Transaction:
        await self._store._lock.acquire()
        self._state = copy.deepcopy(self._store._state)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            self._store._state = self._state
        self._store._lock.release()
        return False

    @property
    def state(self) -> InMemoryState:
        return self._state

    @property
    def fail_on_outbox_job_type(self) -> str | None:
        return self._store._fail_on_outbox_job_type
