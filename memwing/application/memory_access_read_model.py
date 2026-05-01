from __future__ import annotations

from datetime import datetime

from memwing.application.current_truth import CurrentTruthResult
from memwing.application.failure_semantics import classify_failure
from memwing.core.forgetting_curve import compute_decayed_score, effective_last_touched_at
from memwing.core.memory_access import (
    MemoryAccessQuery,
    MemoryAccessResultItem,
    MemoryAccessSearchResult,
)
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResultItem
from memwing.core.models import MemoryItem, MemoryStatus, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.core.validation import SchemaValidationError
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.graph_backend import GraphBackendPort


_CURSOR_PREFIX = "offset:"
_CURRENT_RECALL_STATUSES = frozenset((MemoryStatus.ACTIVE,))
_HISTORY_RECALL_STATUSES = frozenset(
    (
        MemoryStatus.CANDIDATE,
        MemoryStatus.ACTIVE,
        MemoryStatus.FADING,
        MemoryStatus.ARCHIVED,
        MemoryStatus.INVALID,
        MemoryStatus.NEEDS_REVIEW,
    )
)


def rank_memory_items(
    *,
    query: str,
    items: tuple[MemoryItem, ...],
    mode: str,
    min_score: float,
    now: datetime,
) -> list[tuple[MemoryItem, float]]:
    ranked: list[tuple[MemoryItem, float]] = []
    for item in items:
        if not _is_recallable(item, mode=mode):
            continue
        score = memory_item_score(item, now=now)
        if score < min_score:
            continue
        if query and not _matches_query(item, query):
            if mode == "current":
                continue
            score *= 0.5
        ranked.append((item, score))
    return ranked


def sort_ranked_items(
    ranked: list[tuple[MemoryItem, float]],
    *,
    sort: str,
) -> list[tuple[MemoryItem, float]]:
    if sort == "event_time":
        return sorted(
            ranked,
            key=lambda pair: (pair[0].event_time or pair[0].updated_at, pair[0].id),
            reverse=True,
        )
    if sort == "updated_at":
        return sorted(ranked, key=lambda pair: (pair[0].updated_at, pair[0].id), reverse=True)
    return sorted(ranked, key=lambda pair: (pair[1], pair[0].updated_at, pair[0].id), reverse=True)


def memory_item_score(item: MemoryItem, *, now: datetime) -> float:
    if item.cached_decayed_score is not None:
        return item.cached_decayed_score
    return compute_decayed_score(
        original_score=item.original_score,
        effective_last_touched_at=effective_last_touched_at(item),
        now=now,
        half_life_days=item.half_life_days,
    )


def memory_item_in_scope(item: MemoryItem, scope: EffectiveScope) -> bool:
    if item.project_memory_space_id != scope.project_memory_space_id:
        return False
    if scope.thread_id is not None and item.thread_id != scope.thread_id:
        return False
    if scope.group_ids is not None and item.group_id not in scope.group_ids:
        return False
    if scope.shared_group_id is not None and item.shared_group_id != scope.shared_group_id:
        return False
    return True


def source_event_in_scope(event: SourceEvent, scope: EffectiveScope) -> bool:
    if event.project_memory_space_id != scope.project_memory_space_id:
        return False
    if scope.thread_id is not None and event.thread_id != scope.thread_id:
        return False
    if scope.group_ids is not None and event.group_id not in scope.group_ids:
        return False
    if scope.shared_group_id is not None and event.shared_group_id != scope.shared_group_id:
        return False
    return True


def memory_item_to_result_item(
    item: MemoryItem,
    *,
    score: float,
) -> MemoryAccessResultItem:
    return MemoryAccessResultItem(
        id=item.id,
        text=item.content,
        score=score,
        source="memory_item",
        source_event_ids=item.source_event_ids,
        memory_item_ids=(item.id,),
        valid_from=item.valid_from,
        valid_to=item.valid_to,
        metadata={
            "title": item.title,
            "status": item.status.value,
            "route": item.route.value,
            "display_type": item.display_type.value,
            "summary": item.summary,
        },
    )


def current_truth_to_access_result(
    current: CurrentTruthResult,
    *,
    limit: int,
    cursor: str | None = None,
) -> MemoryAccessSearchResult:
    items = (
        *current.current_facts,
        *current.background,
        *current.supporting_evidence,
    )
    if not items:
        items = current.raw_events
    results, next_cursor = paginate_items(
        tuple(memory_search_item_to_access_item(item) for item in items),
        limit=limit,
        cursor=cursor,
    )
    return MemoryAccessSearchResult(
        contexts=tuple(item.text for item in results),
        results=results,
        next_cursor=next_cursor,
        trace_id=current.trace_id,
        warnings=tuple(
            {
                "branch": warning.branch,
                "reason_code": warning.reason_code,
                "message": warning.message,
            }
            for warning in current.warnings
        ),
    )


async def search_graph_history(
    *,
    graph_backend: GraphBackendPort,
    evidence_index: EvidenceIndexPort | None,
    query: MemoryAccessQuery,
    scope: EffectiveScope,
    trace_id: str,
) -> MemoryAccessSearchResult | None:
    fetch_limit = result_fetch_limit(query)
    search_query = MemorySearchQuery(
        query=query.query,
        scope=scope,
        mode="history",
        limit=fetch_limit,
        cursor=None,
        sort=query.sort,
        min_score=query.min_score,
        trace_id=trace_id,
    )
    warnings: tuple[dict[str, str], ...] = ()
    try:
        graph_result = await graph_backend.search_history(search_query)
    except Exception as exc:
        failure = classify_failure(exc, audit_stage="memory_access.graph_history")
        warnings = (
            {
                "branch": "graph_backend",
                "reason_code": failure.reason_code,
                "message": failure.safe_message,
            },
        )
        graph_items: tuple[MemorySearchResultItem, ...] = ()
    else:
        graph_items = graph_result.results

    evidence_items: tuple[MemorySearchResultItem, ...] = ()
    if evidence_index is not None:
        try:
            evidence_items = (await evidence_index.search(search_query)).results
        except Exception as exc:
            failure = classify_failure(exc, audit_stage="memory_access.history_evidence")
            warnings = (
                *warnings,
                {
                    "branch": "evidence_index",
                    "reason_code": failure.reason_code,
                    "message": failure.safe_message,
                },
            )

    items, next_cursor = paginate_items(
        tuple(memory_search_item_to_access_item(item) for item in (*graph_items, *evidence_items)),
        limit=query.limit,
        cursor=query.cursor,
    )
    return MemoryAccessSearchResult(
        contexts=tuple(item.text for item in items),
        results=items,
        next_cursor=next_cursor,
        trace_id=trace_id,
        warnings=warnings,
    )


def result_fetch_limit(query: MemoryAccessQuery) -> int:
    return _cursor_offset(query.cursor) + query.limit + 1


def paginate_items(
    items: tuple[MemoryAccessResultItem, ...],
    *,
    limit: int,
    cursor: str | None,
) -> tuple[tuple[MemoryAccessResultItem, ...], str | None]:
    offset = _cursor_offset(cursor)
    page = items[offset : offset + limit]
    next_offset = offset + limit
    next_cursor = _encode_cursor(next_offset) if len(items) > next_offset else None
    return page, next_cursor


def memory_search_item_to_access_item(item: MemorySearchResultItem) -> MemoryAccessResultItem:
    return MemoryAccessResultItem(
        id=item.id,
        text=item.text,
        score=item.score,
        source=item.source if item.source != "raw_event" else "evidence",
        source_event_ids=item.source_event_ids,
        memory_item_ids=item.memory_item_ids,
        valid_from=item.valid_from,
        valid_to=item.valid_to,
        metadata=item.metadata,
    )


def source_event_to_result_item(
    event: SourceEvent,
    *,
    memory_id: str,
) -> MemoryAccessResultItem:
    return MemoryAccessResultItem(
        id=event.id,
        text=event.content_preview or event.content,
        score=None,
        source="evidence",
        source_event_ids=(event.id,),
        memory_item_ids=(memory_id,),
        valid_from=event.event_time,
        valid_to=None,
        metadata={
            "source_type": event.source_type,
            "author_id": event.author_id,
            "graph_backend_raw_retained": event.graph_backend_raw_retained,
        },
    )


def _is_recallable(item: MemoryItem, *, mode: str) -> bool:
    if item.removed_at is not None or item.status is MemoryStatus.HIDDEN:
        return False
    if mode == "history":
        return item.status in _HISTORY_RECALL_STATUSES
    return item.status in _CURRENT_RECALL_STATUSES


def _matches_query(item: MemoryItem, query: str) -> bool:
    normalized_query = query.casefold()
    searchable = " ".join(
        text for text in (item.title, item.content, item.summary) if text is not None
    ).casefold()
    return normalized_query in searchable


def _cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.startswith(_CURSOR_PREFIX):
        raise SchemaValidationError("memory access cursor is invalid")
    raw_offset = cursor.removeprefix(_CURSOR_PREFIX)
    if not raw_offset.isdecimal():
        raise SchemaValidationError("memory access cursor is invalid")
    return int(raw_offset)


def _encode_cursor(offset: int) -> str:
    return f"{_CURSOR_PREFIX}{offset}"
