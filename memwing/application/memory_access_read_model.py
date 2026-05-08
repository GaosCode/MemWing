from __future__ import annotations

from memwing.application.failure_semantics import classify_failure
from memwing.core.memory_access import (
    MemoryAccessQuery,
    MemoryAccessResultItem,
    MemoryAccessSearchResult,
)
from memwing.core.memory_search import MemorySearchQuery, MemorySearchResultItem
from memwing.core.models import MemoryItem, SourceEvent
from memwing.core.scope import EffectiveScope
from memwing.core.scope_visibility import (
    memory_item_visible_in_scope,
    source_event_visible_in_scope,
)
from memwing.core.validation import SchemaValidationError
from memwing.ports.evidence_index import EvidenceIndexPort
from memwing.ports.graph_backend import GraphBackendPort


_CURSOR_PREFIX = "offset:"


def memory_item_in_scope(item: MemoryItem, scope: EffectiveScope) -> bool:
    return memory_item_visible_in_scope(item, scope)


def source_event_in_scope(event: SourceEvent, scope: EffectiveScope) -> bool:
    return source_event_visible_in_scope(event, scope)


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
        source=item.source,
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
        source="source_event",
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
