from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import uuid

from memwing.core.models import (
    GraphFact,
    GraphWriteJob,
    GraphWriteResult,
    MemoryDisplayType,
    MemoryGraphLink,
    MemoryGraphLinkType,
    MemoryItem,
    MemoryPageVersion,
    MemoryRoute,
    MemoryStatus,
    MemoryVersion,
    PageMemory,
    PageMemoryTopic,
    SourceEvent,
    graph_write_serialization_key,
)
from memwing.ports.benchmark_admin import BenchmarkScope
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.graph_backend import (
    GraphBackendPort,
    GraphWriteBatchRequest,
    GraphWriteRequest,
)


@dataclass(frozen=True, slots=True)
class BenchmarkExpectedMemorySeed:
    id: str
    fact: str
    title: str | None = None
    display_type: MemoryDisplayType = MemoryDisplayType.NOTE
    event_time: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkPreseedExpectedResult:
    source_event_count: int
    memory_item_count: int
    page_memory_count: int
    graph_episode_count: int
    graph_fact_count: int
    memory_item_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    page_ids: tuple[str, ...]
    trace_id: str


class BenchmarkExpectedPreseedWriter:
    def __init__(
        self,
        *,
        unit_of_work: EventStoreUnitOfWorkPort,
        graph_backend: GraphBackendPort | None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._graph_backend = graph_backend

    async def preseed(
        self,
        *,
        scope: BenchmarkScope,
        expected_memories: tuple[BenchmarkExpectedMemorySeed, ...],
        case_id: str | None,
        layers: tuple[str, ...],
        now: datetime | None = None,
    ) -> BenchmarkPreseedExpectedResult:
        if not expected_memories:
            raise ValueError("expected_memories must not be empty")
        selected_layers = _validate_preseed_layers(layers)
        if "graph" in selected_layers and self._graph_backend is None:
            raise ValueError("graph layer requested but graph backend is unavailable")

        seeded_at = now or datetime.now(UTC)
        sources = tuple(
            _expected_source_event(
                scope=scope,
                memory=memory,
                case_id=case_id,
                now=seeded_at,
            )
            for memory in expected_memories
        )
        source_by_memory_id = {
            memory.id: source
            for memory, source in zip(expected_memories, sources, strict=True)
        }
        memory_items = tuple(
            _expected_memory_item(
                scope=scope,
                memory=memory,
                source_event=source_by_memory_id[memory.id],
                now=seeded_at,
            )
            for memory in expected_memories
        )
        page = (
            _expected_page_memory(
                scope=scope,
                case_id=case_id,
                memories=memory_items,
                source_events=sources,
                now=seeded_at,
            )
            if "page_memory" in selected_layers
            else None
        )

        graph_results = ()
        if "graph" in selected_layers:
            graph_results = await self._preseed_graph(
                memory_items=memory_items,
                source_events=sources,
                now=seeded_at,
            )

        async with self._unit_of_work.transaction() as tx:
            for source_event in sources:
                await tx.source_events.insert_if_absent(source_event)
            for item in memory_items:
                await tx.memory_items.upsert(item)
                await tx.memory_versions.record(
                    MemoryVersion(
                        id=_stable_id("benchmark_expected_memory_version", item.id, "1"),
                        memory_id=item.id,
                        version=1,
                        title=item.title,
                        content=item.content,
                        summary=item.summary,
                        status=item.status,
                        source_event_ids=item.source_event_ids,
                        changed_by="system",
                        change_reason="benchmark expected preseed",
                        created_at=seeded_at,
                    )
                )
            if page is not None:
                stored_page = await tx.memory_pages.upsert(page)
                await tx.memory_page_versions.record(
                    MemoryPageVersion(
                        id=_stable_id("benchmark_expected_page_version", stored_page.id, "1"),
                        page_id=stored_page.id,
                        version=stored_page.version,
                        title=stored_page.title,
                        brief=stored_page.brief,
                        topics=stored_page.topics,
                        open_questions=stored_page.open_questions,
                        next_steps=stored_page.next_steps,
                        source_event_ids=stored_page.source_event_ids,
                        linked_memory_item_ids=stored_page.linked_memory_item_ids,
                        changed_by="system",
                        change_reason="benchmark expected preseed",
                        created_at=seeded_at,
                    )
                )
            for item, graph_result in graph_results:
                for link in _graph_links_for_result(
                    item=item,
                    graph_result=graph_result,
                    now=seeded_at,
                ):
                    await tx.memory_graph_links.upsert(link)

        return BenchmarkPreseedExpectedResult(
            source_event_count=len(sources),
            memory_item_count=len(memory_items),
            page_memory_count=1 if page is not None else 0,
            graph_episode_count=sum(
                len(graph_result.backend_episode_refs)
                for _, graph_result in graph_results
            ),
            graph_fact_count=sum(len(graph_result.facts) for _, graph_result in graph_results),
            memory_item_ids=tuple(item.id for item in memory_items),
            source_event_ids=tuple(source.id for source in sources),
            page_ids=(page.id,) if page is not None else (),
            trace_id=f"benchmark_preseed_expected:{scope.project_memory_space_id}",
        )

    async def _preseed_graph(
        self,
        *,
        memory_items: tuple[MemoryItem, ...],
        source_events: tuple[SourceEvent, ...],
        now: datetime,
    ) -> tuple[tuple[MemoryItem, GraphWriteResult], ...]:
        if self._graph_backend is None:
            raise ValueError("graph layer requested but graph backend is unavailable")
        source_by_id = {source.id: source for source in source_events}
        requests = tuple(
            GraphWriteRequest(
                job=_expected_graph_job(item, now=now),
                memory_item=item,
                source_events=tuple(source_by_id[source_id] for source_id in item.source_event_ids),
            )
            for item in memory_items
        )
        batch_result = await self._graph_backend.ingest_graph_jobs(
            GraphWriteBatchRequest(requests=requests)
        )
        result_by_job_id = {item.job_id: item for item in batch_result.items}
        graph_results: list[tuple[MemoryItem, GraphWriteResult]] = []
        for request in requests:
            item_result = result_by_job_id.get(request.job.id)
            if item_result is None or item_result.result is None:
                reason = (
                    item_result.reason_code
                    if item_result is not None and item_result.reason_code is not None
                    else "graph_preseed_failed"
                )
                raise ValueError(reason)
            graph_results.append((request.memory_item, item_result.result))
        return tuple(graph_results)


def _validate_preseed_layers(layers: tuple[str, ...]) -> tuple[str, ...]:
    requested = layers or ("memory_items", "graph", "page_memory")
    allowed = {"memory_items", "graph", "page_memory"}
    unexpected = sorted(set(requested) - allowed)
    if unexpected:
        raise ValueError(f"unsupported preseed layer: {unexpected[0]}")
    if "memory_items" not in requested:
        raise ValueError("memory_items layer is required for expected preseed")
    return tuple(dict.fromkeys(requested))


def _expected_source_event(
    *,
    scope: BenchmarkScope,
    memory: BenchmarkExpectedMemorySeed,
    case_id: str | None,
    now: datetime,
) -> SourceEvent:
    source_id = (
        memory.source_event_ids[0]
        if memory.source_event_ids
        else _stable_id(
            "benchmark_expected_source_event",
            scope.project_memory_space_id,
            memory.id,
        )
    )
    payload = {
        "benchmark_case_id": case_id,
        "expected_memory_id": memory.id,
        "source": "benchmark_expected_preseed",
    }
    return SourceEvent(
        id=source_id,
        project_memory_space_id=scope.project_memory_space_id,
        group_id=scope.group_id,
        thread_id=scope.thread_id,
        shared_group_id=scope.shared_group_id,
        author_id="benchmark",
        author_name="Benchmark",
        source_type="benchmark.expected_memory",
        content=memory.fact,
        content_preview=memory.fact[:240],
        source_url=None,
        event_time=memory.event_time or now,
        raw_payload_hash=_hash_payload(scope.project_memory_space_id, memory.id, memory.fact),
        metadata={
            "source_ref": {"kind": "benchmark_expected", "case_id": case_id},
            "adapter_metadata": {"payload": payload},
        },
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=now,
        runtime_event_idempotency_key=f"benchmark_expected:{scope.project_memory_space_id}:{memory.id}",
    )


def _expected_memory_item(
    *,
    scope: BenchmarkScope,
    memory: BenchmarkExpectedMemorySeed,
    source_event: SourceEvent,
    now: datetime,
) -> MemoryItem:
    memory_id = _stable_id("benchmark_expected_memory_item", scope.project_memory_space_id, memory.id)
    title = memory.title or _memory_title(memory.fact)
    return MemoryItem(
        id=memory_id,
        project_memory_space_id=scope.project_memory_space_id,
        group_id=scope.group_id,
        thread_id=scope.thread_id,
        shared_group_id=scope.shared_group_id,
        route=MemoryRoute.GRAPH,
        display_type=memory.display_type,
        title=title,
        content=memory.fact,
        summary=memory.fact,
        source_event_ids=(source_event.id,),
        primary_source_event_id=source_event.id,
        status=MemoryStatus.ACTIVE,
        event_time=memory.event_time or source_event.event_time,
        valid_from=memory.valid_from or memory.event_time or source_event.event_time,
        valid_to=memory.valid_to,
        original_score=1.0,
        half_life_days=3650,
        last_reviewed_at=None,
        last_confirmed_at=now,
        last_recalled_at=None,
        recall_count=0,
        cached_decayed_score=None,
        last_decay_computed_at=None,
        pinned=False,
        created_by="system",
        created_at=now,
        activated_at=now,
        updated_at=now,
        archived_at=None,
        hidden_at=None,
        invalidated_at=None,
        removed_at=None,
        lifecycle_revision=0,
    )


def _expected_page_memory(
    *,
    scope: BenchmarkScope,
    case_id: str | None,
    memories: tuple[MemoryItem, ...],
    source_events: tuple[SourceEvent, ...],
    now: datetime,
) -> PageMemory:
    scope_type = "thread" if scope.thread_id is not None else "project"
    scope_id = scope.thread_id or scope.project_memory_space_id
    title = f"Benchmark expected memory: {case_id or scope_id}"
    topics = tuple(
        PageMemoryTopic(
            title=item.title,
            summary=item.content,
            source_event_ids=item.source_event_ids,
            linked_memory_item_ids=(item.id,),
        )
        for item in memories
    )
    return PageMemory(
        id=_stable_id("benchmark_expected_page_memory", scope.project_memory_space_id, scope_id),
        project_memory_space_id=scope.project_memory_space_id,
        group_id=scope.group_id,
        thread_id=scope.thread_id,
        shared_group_id=scope.shared_group_id,
        scope_type=scope_type,
        scope_id=scope_id,
        title=title,
        brief="\n".join(f"- {item.content}" for item in memories),
        topics=topics,
        open_questions=(),
        next_steps=(),
        source_event_ids=tuple(source.id for source in source_events),
        linked_memory_item_ids=tuple(item.id for item in memories),
        version=1,
        needs_rebuild=False,
        created_at=now,
        updated_at=now,
    )


def _expected_graph_job(item: MemoryItem, *, now: datetime) -> GraphWriteJob:
    return GraphWriteJob(
        id=_stable_id("benchmark_expected_graph_job", item.project_memory_space_id, item.id),
        backend="graphiti",
        serialization_key=graph_write_serialization_key(
            backend="graphiti",
            project_memory_space_id=item.project_memory_space_id,
        ),
        project_memory_space_id=item.project_memory_space_id,
        thread_id=item.thread_id,
        saga_id=item.thread_id,
        memory_id=item.id,
        source_event_ids=item.source_event_ids,
        route=item.route,
        status="succeeded",
        idempotency_key=f"benchmark_expected_graph:{item.project_memory_space_id}:{item.id}",
        attempts=1,
        max_attempts=1,
        priority=0,
        next_run_at=now,
        dead_letter_reason=None,
        last_error=None,
        locked_at=None,
        locked_by=None,
        lock_expires_at=None,
        created_at=now,
        updated_at=now,
    )


def _graph_links_for_result(
    *,
    item: MemoryItem,
    graph_result: GraphWriteResult,
    now: datetime,
) -> tuple[MemoryGraphLink, ...]:
    links: list[MemoryGraphLink] = []
    source_event_id = item.source_event_ids[0]
    for episode_ref in graph_result.backend_episode_refs:
        links.append(
            _graph_link(
                item=item,
                source_event_id=source_event_id,
                backend=graph_result.backend,
                backend_object_type="episode",
                backend_object_id=episode_ref,
                link_type="episode",
                now=now,
            )
        )
    for fact in graph_result.facts:
        if not isinstance(fact, GraphFact) or not fact.source_event_ids:
            raise ValueError("graph fact missing source event ids")
        links.append(
            _graph_link(
                item=item,
                source_event_id=fact.source_event_ids[0],
                backend=graph_result.backend,
                backend_object_type="fact",
                backend_object_id=fact.fact_id,
                link_type="fact",
                now=now,
            )
        )
    return tuple(links)


def _graph_link(
    *,
    item: MemoryItem,
    source_event_id: str,
    backend: str,
    backend_object_type: str,
    backend_object_id: str,
    link_type: MemoryGraphLinkType,
    now: datetime,
) -> MemoryGraphLink:
    return MemoryGraphLink(
        id=_stable_id(
            "benchmark_expected_graph_link",
            item.project_memory_space_id,
            item.id,
            backend,
            backend_object_type,
            backend_object_id,
        ),
        backend=backend,
        memory_id=item.id,
        source_event_id=source_event_id,
        project_memory_space_id=item.project_memory_space_id,
        backend_space_id=item.project_memory_space_id,
        backend_object_type=backend_object_type,
        backend_object_id=backend_object_id,
        link_type=link_type,
        created_at=now,
    )


def _memory_title(fact: str) -> str:
    stripped = " ".join(fact.split())
    return stripped[:60] if len(stripped) > 60 else stripped


def _stable_id(namespace: str, *parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join((namespace, *parts))))


def _hash_payload(*parts: str) -> str:
    return sha256("\n".join(parts).encode("utf-8")).hexdigest()
