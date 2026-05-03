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
    postgres: dict[str, object]
    graph: dict[str, object]
    evidence: dict[str, object]
    page_memory: dict[str, object]
    memory_items: dict[str, object]
    warnings: tuple[dict[str, str], ...]
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
        postgres_summary = await self._postgres_summary(effective_scope)
        job_summary = await self._job_summary(scope.project_memory_space_id)
        query_summaries = tuple(
            [
                await self._query_summary(
                    query_text=query,
                    scope=effective_scope,
                    limit=5,
                    postgres_summary=postgres_summary,
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
        warnings = tuple(
            warning
            for query in query_summaries
            for warning in query["warnings"]
            if isinstance(warning, dict)
        )
        return BenchmarkReadinessResult(
            ready=ready,
            postgres=postgres_summary,
            graph=_aggregate_backend_readiness(
                branch="graph",
                enabled=self._graph_backend is not None,
                queries=query_summaries,
            ),
            evidence=_aggregate_backend_readiness(
                branch="evidence",
                enabled=self._evidence_index is not None,
                queries=query_summaries,
            ),
            page_memory={
                "ready": postgres_summary["page_memory"] > 0,
                "count": postgres_summary["page_memory"],
            },
            memory_items={"count": postgres_summary["memory_items"]},
            warnings=warnings,
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

    async def _postgres_summary(self, scope: EffectiveScope) -> dict[str, object]:
        async with self._unit_of_work.transaction() as tx:
            source_events = await tx.source_events.list_for_scope(scope=scope, limit=10000)
            memory_items = await tx.memory_items.list_for_scope(scope=scope, limit=10000)
            pages = await tx.memory_pages.list_for_scope(scope=scope, limit=10000)
        return {
            "source_events": len(source_events),
            "memory_items": len(memory_items),
            "page_memory": len(pages),
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
        postgres_summary: dict[str, object],
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
        graph_results: list[dict[str, object]] = []
        evidence_results: list[dict[str, object]] = []
        warnings: list[dict[str, str]] = []
        if self._graph_backend is not None:
            try:
                graph_result = await self._graph_backend.search_current(search_query)
            except Exception as exc:
                warnings.append(_warning("graph_backend", exc))
            else:
                graph_results.extend(_result_refs(graph_result.results))
        if self._evidence_index is not None:
            try:
                evidence_result = await self._evidence_index.search(search_query)
            except Exception as exc:
                warnings.append(_warning("evidence_index", exc))
            else:
                evidence_results.extend(_result_refs(evidence_result.results))

        results = [*graph_results, *evidence_results]
        source_mix = dict(Counter(str(result["source"]) for result in results))
        return {
            "query": query_text,
            "result_count": len(results),
            "source_mix": source_mix,
            "graph": _branch_readiness(
                enabled=self._graph_backend is not None,
                results=graph_results,
                warnings=warnings,
                warning_branch="graph_backend",
            ),
            "evidence": _branch_readiness(
                enabled=self._evidence_index is not None,
                results=evidence_results,
                warnings=warnings,
                warning_branch="evidence_index",
            ),
            "page_memory": {
                "ready": postgres_summary["page_memory"] > 0,
                "count": postgres_summary["page_memory"],
            },
            "memory_items": {"count": postgres_summary["memory_items"]},
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
                "source_event_ids": tuple(getattr(result, "source_event_ids")),
            }
        )
    return refs


def _branch_readiness(
    *,
    enabled: bool,
    results: list[dict[str, object]],
    warnings: list[dict[str, str]],
    warning_branch: str,
) -> dict[str, object]:
    branch_warnings = tuple(warning for warning in warnings if warning["branch"] == warning_branch)
    return {
        "enabled": enabled,
        "ready": enabled and not branch_warnings and bool(results),
        "result_count": len(results),
        "matched_source_event_ids": _matched_source_event_ids(results),
        "warnings": branch_warnings,
    }


def _aggregate_backend_readiness(
    *,
    branch: str,
    enabled: bool,
    queries: tuple[dict[str, object], ...],
) -> dict[str, object]:
    branch_summaries = [
        query[branch]
        for query in queries
        if isinstance(query.get(branch), dict)
    ]
    matched = tuple(
        source_event_id
        for summary in branch_summaries
        for source_event_id in summary["matched_source_event_ids"]
        if isinstance(source_event_id, str)
    )
    warnings = tuple(
        warning
        for summary in branch_summaries
        for warning in summary["warnings"]
        if isinstance(warning, dict)
    )
    return {
        "enabled": enabled,
        "ready": enabled and not warnings and bool(matched),
        "matched_source_event_ids": tuple(dict.fromkeys(matched)),
        "warnings": warnings,
    }


def _matched_source_event_ids(results: list[dict[str, object]]) -> tuple[str, ...]:
    matched: list[str] = []
    for result in results:
        source_event_ids = result.get("source_event_ids")
        if not isinstance(source_event_ids, tuple):
            continue
        matched.extend(source_event_id for source_event_id in source_event_ids if source_event_id)
    return tuple(dict.fromkeys(matched))


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
