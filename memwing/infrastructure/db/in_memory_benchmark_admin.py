from __future__ import annotations

from collections.abc import Callable

from memwing.core.scope import GroupMemorySettings, ProjectMemorySpace, RuntimeScopeBinding
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.db.in_memory_state import InMemoryState
from memwing.ports.benchmark_admin import (
    BenchmarkAdminStorePort,
    BenchmarkCleanupResult,
    BenchmarkRuntimeBinding,
    BenchmarkScope,
)


class InMemoryBenchmarkAdminStore(BenchmarkAdminStorePort):
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def prepare_scope(
        self,
        *,
        scope: BenchmarkScope,
        runtime_binding: BenchmarkRuntimeBinding,
    ) -> None:
        _prepare_scope_state(
            self._store._state,
            scope=scope,
            runtime_binding=runtime_binding,
        )

    async def cleanup_scope(
        self,
        *,
        scope: BenchmarkScope,
        runtime_binding: BenchmarkRuntimeBinding,
    ) -> BenchmarkCleanupResult:
        state = self._store._state
        project_id = scope.project_memory_space_id

        source_ids = {
            source_id
            for source_id, event in state.source_events.items()
            if event.project_memory_space_id == project_id
        }
        memory_ids = {
            memory_id
            for memory_id, item in state.memory_items.items()
            if item.project_memory_space_id == project_id
        }
        page_ids = {
            page_id
            for page_id, page in state.memory_pages.items()
            if page.project_memory_space_id == project_id
        }

        deleted_counts: dict[str, int] = {}
        deleted_counts["memory_recall_events"] = _delete_matching(
            state.memory_recall_events,
            lambda event: event.project_memory_space_id == project_id,
        )
        deleted_counts["memory_graph_links"] = _delete_matching(
            state.memory_graph_links,
            lambda link: link.project_memory_space_id == project_id,
        )
        deleted_counts["graph_write_jobs"] = _delete_matching(
            state.graph_write_jobs,
            lambda job: job.project_memory_space_id == project_id,
        )
        deleted_counts["memory_page_versions"] = _delete_matching(
            state.memory_page_versions,
            lambda version: version.page_id in page_ids,
        )
        deleted_counts["memory_pages"] = _delete_matching(
            state.memory_pages,
            lambda page: page.project_memory_space_id == project_id,
        )
        deleted_counts["memory_versions"] = _delete_matching(
            state.memory_versions,
            lambda version: version.memory_id in memory_ids,
        )
        deleted_counts["push_candidates"] = _delete_matching(
            state.push_candidates,
            lambda candidate: candidate.project_memory_space_id == project_id,
        )
        deleted_counts["forgetting_review_candidates"] = _delete_matching(
            state.forgetting_review_candidates,
            lambda candidate: candidate.project_memory_space_id == project_id,
        )
        deleted_counts["memory_items"] = _delete_matching(
            state.memory_items,
            lambda item: item.project_memory_space_id == project_id,
        )
        deleted_counts["working_memory_entries"] = _delete_matching(
            state.working_memory_entries,
            lambda entry: entry.project_memory_space_id == project_id,
        )
        deleted_counts["evidence_chunks"] = _delete_matching(
            state.evidence_chunks,
            lambda chunk: chunk.project_memory_space_id == project_id,
        )
        deleted_counts["outbox_jobs"] = _delete_matching(
            state.outbox_jobs,
            lambda job: job.project_memory_space_id == project_id,
        )
        deleted_counts["audit_events"] = _delete_matching(
            state.audit_events,
            lambda event: event.entity_id == project_id
            or event.entity_id in source_ids
            or event.entity_id in memory_ids
            or bool(set(event.source_event_ids) & source_ids),
        )
        deleted_counts["source_events"] = _delete_matching(
            state.source_events,
            lambda event: event.project_memory_space_id == project_id,
        )

        state.source_by_raw_hash = {
            key: source_id
            for key, source_id in state.source_by_raw_hash.items()
            if source_id in state.source_events
        }
        state.source_by_runtime_key = {
            key: source_id
            for key, source_id in state.source_by_runtime_key.items()
            if source_id in state.source_events
        }
        state.outbox_by_idempotency_key = {
            key: job_id
            for key, job_id in state.outbox_by_idempotency_key.items()
            if job_id in state.outbox_jobs
        }
        state.graph_job_by_idempotency_key = {
            key: job_id
            for key, job_id in state.graph_job_by_idempotency_key.items()
            if job_id in state.graph_write_jobs
        }
        state.evidence_by_source_chunk = {
            key: chunk_id
            for key, chunk_id in state.evidence_by_source_chunk.items()
            if chunk_id in state.evidence_chunks
        }
        state.working_memory_by_scope_sequence = {
            key: entry_id
            for key, entry_id in state.working_memory_by_scope_sequence.items()
            if entry_id in state.working_memory_entries
        }
        state.memory_version_by_memory_version = {
            key: version_id
            for key, version_id in state.memory_version_by_memory_version.items()
            if version_id in state.memory_versions
        }
        state.memory_page_by_scope = {
            key: page_id
            for key, page_id in state.memory_page_by_scope.items()
            if page_id in state.memory_pages
        }
        state.memory_page_version_by_page_version = {
            key: version_id
            for key, version_id in state.memory_page_version_by_page_version.items()
            if version_id in state.memory_page_versions
        }
        state.memory_graph_link_by_backend_object = {
            key: link_id
            for key, link_id in state.memory_graph_link_by_backend_object.items()
            if link_id in state.memory_graph_links
        }
        state.forgetting_review_by_memory_reason_status = {
            key: candidate_id
            for key, candidate_id in state.forgetting_review_by_memory_reason_status.items()
            if candidate_id in state.forgetting_review_candidates
        }
        state.push_candidate_by_cooldown_status = {
            key: candidate_id
            for key, candidate_id in state.push_candidate_by_cooldown_status.items()
            if candidate_id in state.push_candidates
        }

        _prepare_scope_state(state, scope=scope, runtime_binding=runtime_binding)
        return BenchmarkCleanupResult(deleted_counts=deleted_counts, prepared=True)


def _delete_matching(values: dict[str, object], predicate: Callable[[object], bool]) -> int:
    keys = [key for key, value in values.items() if predicate(value)]
    for key in keys:
        del values[key]
    return len(keys)


def _prepare_scope_state(
    state: InMemoryState,
    *,
    scope: BenchmarkScope,
    runtime_binding: BenchmarkRuntimeBinding,
) -> None:
    project_id = scope.project_memory_space_id
    state.projects[project_id] = ProjectMemorySpace(
        id=project_id,
        name=f"Benchmark {project_id}",
        default_safe_mode_enabled=False,
    )
    if scope.group_id is not None:
        state.group_settings[(project_id, scope.group_id)] = GroupMemorySettings(
            project_memory_space_id=project_id,
            group_id=scope.group_id,
            safe_mode_enabled=True,
            shared_group_id=scope.shared_group_id,
        )
    state.runtime_bindings = [
        binding
        for binding in state.runtime_bindings
        if binding.project_memory_space_id != project_id
    ]
    state.runtime_bindings.append(
        RuntimeScopeBinding(
            runtime=runtime_binding.runtime,
            agent_id=runtime_binding.agent_id,
            workspace_id=runtime_binding.workspace_id,
            session_key_pattern=runtime_binding.session_id or "",
            project_memory_space_id=project_id,
        )
    )
