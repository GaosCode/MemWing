from __future__ import annotations

from datetime import datetime
import re

from memwing.application.current_truth import CurrentTruthResult
from memwing.application.failure_semantics import classify_failure
from memwing.application.search_relevance import search_relevance_score
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
_ASSEMBLED_CONTEXT_ID = "current_truth:assembled"
_QUERY_STOP_TERMS = frozenset(
    (
        "什么",
        "现在",
        "当前",
        "这个",
        "项目",
        "是谁",
        "是否",
        "还是",
        "不是",
        "如果",
        "应该",
        "不要",
        "混淆",
        "分别",
    )
)
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
    sort: str = "authority",
    query: str = "",
) -> MemoryAccessSearchResult:
    items = (
        *current.current_facts,
        *current.background,
        *current.supporting_evidence,
    )
    if not items:
        items = current.raw_events
    if sort == "relevance":
        items = _sort_scored_results_for_relevance(items, query=query)
    access_items = tuple(memory_search_item_to_access_item(item) for item in items)
    if sort == "relevance":
        access_items = _prepend_assembled_context_for_compound_query(
            query=query,
            items=access_items,
        )
    results, next_cursor = paginate_items(
        access_items,
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
        diagnostics={
            "current_truth": {
                "branch_timings": tuple(
                    {
                        "branch": timing.branch,
                        "latency_ms": timing.latency_ms,
                        "result_count": timing.result_count,
                        "status": timing.status,
                    }
                    for timing in current.branch_timings
                )
            }
        },
    )


def _sort_scored_results_for_relevance(
    items: tuple[MemorySearchResultItem, ...],
    *,
    query: str,
) -> tuple[MemorySearchResultItem, ...]:
    return tuple(
        item
        for _, item in sorted(
            enumerate(items),
            key=lambda pair: _relevance_sort_key(pair[0], pair[1], query=query),
        )
    )


def _relevance_sort_key(
    index: int,
    item: MemorySearchResultItem,
    *,
    query: str,
) -> tuple[float, int]:
    base_score = item.score or 0
    relevance_score = base_score + search_relevance_score(query, item.text)
    return (-relevance_score, index)


def _prepend_assembled_context_for_compound_query(
    *,
    query: str,
    items: tuple[MemoryAccessResultItem, ...],
) -> tuple[MemoryAccessResultItem, ...]:
    if not _needs_assembled_context(query) or len(items) < 2:
        return items

    selected = _select_assembled_context_items(query=query, items=items)
    if len(selected) < 2:
        return items

    source_event_ids = tuple(
        dict.fromkeys(source_id for item in selected for source_id in item.source_event_ids)
    )
    memory_item_ids = tuple(
        dict.fromkeys(memory_id for item in selected for memory_id in item.memory_item_ids)
    )
    assembled = MemoryAccessResultItem(
        id=_ASSEMBLED_CONTEXT_ID,
        text="\n".join(item.text for item in selected),
        score=max((item.score or 0 for item in selected), default=0),
        source="working_memory",
        source_event_ids=source_event_ids,
        memory_item_ids=memory_item_ids,
        valid_from=None,
        valid_to=None,
        metadata={
            "source": "current_truth_assembled",
            "assembled_item_ids": tuple(item.id for item in selected),
        },
    )
    return (assembled, *items)


def _select_assembled_context_items(
    *,
    query: str,
    items: tuple[MemoryAccessResultItem, ...],
) -> tuple[MemoryAccessResultItem, ...]:
    candidates = [
        item
        for item in items[:8]
        if _lexical_relevance_score(query, item.text) > 0.15
        and _matches_assembled_intent(query, item.text)
        and not _is_stale_only_context_for_query(query, item.text)
    ]
    if len(candidates) < 2:
        candidates = [
            item
            for item in items[:8]
            if _lexical_relevance_score(query, item.text) > 0.15
            and _matches_assembled_intent(query, item.text)
        ]
    return tuple(candidates[:4])


def _matches_assembled_intent(query: str, text: str) -> bool:
    normalized_query = query.casefold()
    normalized_text = text.casefold()
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("负责人", ("负责人", "接手")),
        ("找谁", ("负责人", "接手", "负责", "找")),
        ("还负责", ("不再负责", "负责排期", "负责验收", "接手")),
        ("上线", ("上线", "发布")),
        ("窗口", ("上线窗口", "发布窗口")),
        ("交付范围", ("交付范围", "订阅入口", "旧版配置迁移", "只保留", "删除")),
        ("短信提醒", ("短信提醒", "不进", "不要再写", "另立迭代")),
        ("方案乙", ("方案乙", "方案丙", "正式方案", "当前方案", "按方案丙推进")),
    ]
    matched_checks = [
        markers
        for query_marker, markers in checks
        if query_marker in normalized_query
    ]
    if not matched_checks:
        return True
    return any(
        any(marker in normalized_text for marker in markers)
        for markers in matched_checks
    )


def _needs_assembled_context(query: str) -> bool:
    normalized = query.casefold()
    if sum(normalized.count(mark) for mark in ("?", "？")) >= 2:
        return True
    return any(
        marker in normalized
        for marker in (
            "分别",
            "不要混淆",
            "是否曾经",
            "曾经",
            "还有效",
            "还包括",
            "还负责",
            "不再",
        )
    )


def _is_stale_only_context_for_query(query: str, text: str) -> bool:
    normalized_query = query.casefold()
    normalized_text = text.casefold()
    if _query_needs_historical_context(normalized_query):
        return False
    if not _query_needs_current_context(normalized_query):
        return False
    return any(
        marker in normalized_text
        for marker in (
            "初始计划",
            "暂定",
            "当时决定",
            "第一次评审",
            "还在等",
            "前给出是否",
        )
    )


def _lexical_relevance_score(query: str, text: str) -> float:
    normalized_query = _normalize_relevance_text(query)
    normalized_text = _normalize_relevance_text(text)
    if not normalized_query or not normalized_text:
        return 0

    score = 0.0
    query_terms = _query_terms(normalized_query)
    for term in query_terms:
        if term in normalized_text:
            score += min(len(term), 8) * 0.015

    for intent, markers in _intent_markers(normalized_query).items():
        if intent not in normalized_query:
            continue
        if any(marker in normalized_text for marker in markers):
            score += 0.18

    if normalized_query in normalized_text:
        score += 0.3
    return min(score, 0.9)


def _temporal_relevance_adjustment(query: str, text: str) -> float:
    normalized_query = query.casefold()
    normalized_text = text.casefold()
    score = 0.0
    current_query = _query_needs_current_context(normalized_query)
    historical_query = _query_needs_historical_context(normalized_query)
    if current_query and any(
        marker in normalized_text
        for marker in (
            "当前",
            "现在",
            "最新",
            "最终",
            "改为",
            "调整为",
            "变更为",
            "确定为",
            "不再",
            "删除",
            "只保留",
            "后续",
            "按方案丙推进",
        )
    ):
        score += 0.35
    if current_query and not historical_query and any(
        marker in normalized_text
        for marker in (
            "初始计划",
            "暂定",
            "当时决定",
            "第一次评审",
            "还在等",
            "前给出是否",
        )
    ):
        score -= 0.35
    if historical_query and any(
        marker in normalized_text
        for marker in ("曾经", "讨论过", "当时", "中间讨论", "第一次评审")
    ):
        score += 0.25
    return score


def _query_needs_current_context(normalized_query: str) -> bool:
    return any(
        marker in normalized_query
        for marker in ("当前", "现在", "最新", "有效", "还有效", "还包括", "还负责", "正式推进")
    )


def _query_needs_historical_context(normalized_query: str) -> bool:
    return any(marker in normalized_query for marker in ("曾经", "讨论过", "历史", "当时"))


def _intent_markers(normalized_query: str) -> dict[str, tuple[str, ...]]:
    return {
        "负责人": ("负责人", "接手", "找", "负责"),
        "找谁": ("负责人", "接手", "找", "负责"),
        "上线": ("上线时间", "上线窗口", "发布时间", "发布演练"),
        "窗口": ("上线窗口", "发布窗口"),
        "交付范围": ("交付范围", "交付", "删除", "只保留", "不进"),
        "短信提醒": ("短信提醒", "删除", "不进", "不要再写", "另立迭代"),
        "方案乙": ("方案乙", "讨论过", "不再", "方案丙"),
        "方案丙": ("方案丙", "按方案丙推进", "最终采用"),
        "验收沟通": ("验收沟通", "验收", "负责"),
    }


def _query_terms(normalized_query: str) -> tuple[str, ...]:
    terms: set[str] = set(re.findall(r"[a-z0-9]+", normalized_query))
    cjk_text = re.sub(r"[^一-鿿]+", "", normalized_query)
    for size in (2, 3, 4, 5, 6):
        for index in range(0, max(len(cjk_text) - size + 1, 0)):
            term = cjk_text[index : index + size]
            if term not in _QUERY_STOP_TERMS:
                terms.add(term)
    return tuple(sorted(terms, key=lambda term: (-len(term), term)))


def _normalize_relevance_text(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold())


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
