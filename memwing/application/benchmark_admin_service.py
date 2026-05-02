from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from memwing.core.memory_search import MemorySearchQuery
from memwing.core.scope import EffectiveScope
from memwing.ports.benchmark_admin import (
    BenchmarkAdminStorePort,
    BenchmarkCleanupResult,
    BenchmarkRuntimeBinding,
    BenchmarkScope,
)
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import GraphBackendPort
from memwing.workers.benchmark_drain import BenchmarkDrainResult, BenchmarkDrainWorker


@dataclass(frozen=True, slots=True)
class BenchmarkReadinessResult:
    ready: bool
    source_events: dict[str, object]
    jobs: dict[str, object]
    backends: dict[str, object]
    queries: tuple[dict[str, object], ...]


class BenchmarkAdminService:
    def __init__(
        self,
        *,
        unit_of_work: EventStoreUnitOfWorkPort,
        admin_store: BenchmarkAdminStorePort,
        drain_worker: BenchmarkDrainWorker,
        graph_backend: GraphBackendPort | None,
        evidence_index: EvidenceIndexPort | None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._admin_store = admin_store
        self._drain_worker = drain_worker
        self._graph_backend = graph_backend
        self._evidence_index = evidence_index

    async def cleanup_scope(
        self,
        *,
        scope: BenchmarkScope,
        runtime_binding: BenchmarkRuntimeBinding,
    ) -> BenchmarkCleanupResult:
        _require_benchmark_scope(scope)
        return await self._admin_store.cleanup_scope(
            scope=scope,
            runtime_binding=runtime_binding,
        )

    async def drain_scope(
        self,
        *,
        scope: BenchmarkScope,
        max_iterations: int,
        batch_size: int,
    ) -> BenchmarkDrainResult:
        _require_benchmark_scope(scope)
        return await self._drain_worker.drain_scope(
            scope=_effective_scope(scope),
            max_iterations=max_iterations,
            batch_size=batch_size,
        )

    async def readiness(
        self,
        *,
        scope: BenchmarkScope,
        expected_source_event_ids: tuple[str, ...],
        queries: tuple[str, ...],
    ) -> BenchmarkReadinessResult:
        _require_benchmark_scope(scope)
        effective_scope = _effective_scope(scope)
        source_summary = await self._source_summary(
            expected_source_event_ids=expected_source_event_ids,
            scope=effective_scope,
        )
        job_summary = await self._job_summary(scope.project_memory_space_id)
        query_summaries = tuple(
            [
                await self._query_summary(
                    query_text=query,
                    scope=effective_scope,
                    limit=5,
                )
                for query in queries
            ]
        )
        backend_summary = _backend_summary(
            graph_backend=self._graph_backend,
            evidence_index=self._evidence_index,
            queries=query_summaries,
        )
        ready = (
            source_summary["missing_count"] == 0
            and job_summary["pending_count"] == 0
            and job_summary["processing_count"] == 0
            and job_summary["dead_letter_count"] == 0
            and backend_summary["unavailable_count"] == 0
            and backend_summary["enabled_count"] > 0
            and all(summary["result_count"] > 0 for summary in query_summaries)
        )
        return BenchmarkReadinessResult(
            ready=ready,
            source_events=source_summary,
            jobs=job_summary,
            backends=backend_summary,
            queries=query_summaries,
        )

    async def _source_summary(
        self,
        *,
        expected_source_event_ids: tuple[str, ...],
        scope: EffectiveScope,
    ) -> dict[str, object]:
        loaded: list[str] = []
        async with self._unit_of_work.transaction() as tx:
            for source_event_id in expected_source_event_ids:
                source_event = await tx.source_events.get_source_event(source_event_id)
                if source_event is None:
                    continue
                if source_event.project_memory_space_id != scope.project_memory_space_id:
                    continue
                loaded.append(source_event.id)
        missing = tuple(
            source_event_id
            for source_event_id in expected_source_event_ids
            if source_event_id not in loaded
        )
        return {
            "expected_count": len(expected_source_event_ids),
            "available_count": len(loaded),
            "missing_count": len(missing),
            "missing_source_event_ids": missing,
        }

    async def _job_summary(self, project_memory_space_id: str) -> dict[str, object]:
        async with self._unit_of_work.transaction() as tx:
            outbox_jobs = await tx.outbox_jobs.list_for_project(
                project_memory_space_id=project_memory_space_id,
                limit=10000,
            )
            graph_jobs = await tx.graph_write_jobs.list_for_project(
                project_memory_space_id=project_memory_space_id,
                limit=10000,
            )
        outbox_counts = Counter(job.status for job in outbox_jobs)
        graph_counts = Counter(job.status for job in graph_jobs)
        pending_count = (
            outbox_counts["pending"]
            + graph_counts["pending"]
        )
        processing_count = (
            outbox_counts["processing"]
            + graph_counts["processing"]
        )
        dead_letter_count = outbox_counts["dead_letter"] + graph_counts["dead_letter"]
        return {
            "outbox": dict(outbox_counts),
            "graph_write": dict(graph_counts),
            "pending_count": pending_count,
            "processing_count": processing_count,
            "dead_letter_count": dead_letter_count,
        }

    async def _query_summary(
        self,
        *,
        query_text: str,
        scope: EffectiveScope,
        limit: int,
    ) -> dict[str, object]:
        search_query = MemorySearchQuery(
            query=query_text,
            scope=scope,
            mode="current",
            limit=limit,
            cursor=None,
            sort="relevance",
            min_score=0.0,
            trace_id=f"benchmark_readiness:{scope.project_memory_space_id}",
        )
        results: list[dict[str, object]] = []
        warnings: list[dict[str, str]] = []
        if self._graph_backend is not None:
            try:
                graph_result = await self._graph_backend.search_current(search_query)
            except Exception as exc:
                warnings.append(_warning("graph_backend", exc))
            else:
                results.extend(_result_refs(graph_result.results))
        if self._evidence_index is not None:
            try:
                evidence_result = await self._evidence_index.search(search_query)
            except Exception as exc:
                warnings.append(_warning("evidence_index", exc))
            else:
                results.extend(_result_refs(evidence_result.results))

        source_mix = dict(Counter(str(result["source"]) for result in results))
        return {
            "query": query_text,
            "result_count": len(results),
            "source_mix": source_mix,
            "warnings": tuple(warnings),
        }


def _backend_summary(
    *,
    graph_backend: GraphBackendPort | None,
    evidence_index: EvidenceIndexPort | None,
    queries: tuple[dict[str, object], ...],
) -> dict[str, object]:
    enabled = {
        "graph_backend": graph_backend is not None,
        "evidence_index": evidence_index is not None,
    }
    warnings = [
        warning
        for query in queries
        for warning in query["warnings"]
        if isinstance(warning, dict)
    ]
    unavailable = Counter(warning["branch"] for warning in warnings)
    return {
        "enabled": enabled,
        "enabled_count": sum(1 for value in enabled.values() if value),
        "unavailable": dict(unavailable),
        "unavailable_count": sum(unavailable.values()),
    }


def _result_refs(results: tuple[object, ...]) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for result in results:
        refs.append(
            {
                "id": getattr(result, "id"),
                "source": getattr(result, "source"),
            }
        )
    return refs


def _warning(branch: str, exc: Exception) -> dict[str, str]:
    return {
        "branch": branch,
        "reason_code": exc.__class__.__name__,
        "message": "backend unavailable during benchmark readiness",
    }


def _require_benchmark_scope(scope: BenchmarkScope) -> None:
    if not scope.project_memory_space_id.startswith("benchmark:"):
        raise ValueError("benchmark admin scope must use project_memory_space_id prefix benchmark:")


def _effective_scope(scope: BenchmarkScope) -> EffectiveScope:
    return EffectiveScope(
        project_memory_space_id=scope.project_memory_space_id,
        group_ids=(scope.group_id,) if scope.group_id is not None else None,
        thread_id=scope.thread_id,
        shared_group_id=scope.shared_group_id,
        safe_mode_enabled=scope.group_id is not None,
        cross_group_allowed=scope.group_id is None,
    )

