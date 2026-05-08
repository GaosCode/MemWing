from __future__ import annotations

from datetime import datetime

from memwing.application.search_relevance import search_relevance_matches, search_relevance_score
from memwing.core.forgetting_curve import compute_decayed_score, effective_last_touched_at
from memwing.core.models import MemoryItem, MemoryStatus


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
_RAW_FALLBACK_BLOCKING_STATUSES = frozenset(
    (
        MemoryStatus.CANDIDATE,
        MemoryStatus.ACTIVE,
        MemoryStatus.FADING,
        MemoryStatus.ARCHIVED,
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
        if not is_recallable_memory_item(item, mode=mode):
            continue
        score = memory_item_score(item, now=now)
        if score < min_score:
            continue
        if query and not memory_item_matches_query(item, query):
            if mode == "current":
                continue
            score *= 0.5
        ranked.append((item, score))
    return ranked


def rank_current_memory_items(
    *,
    query: str,
    items: tuple[MemoryItem, ...],
    min_score: float,
    now: datetime,
) -> list[tuple[MemoryItem, float]]:
    ranked: list[tuple[MemoryItem, float]] = []
    for item in items:
        if not is_current_recallable_memory_item(item):
            continue
        score = memory_item_score(item, now=now)
        if score < min_score:
            continue
        searchable = memory_item_search_text(item)
        relevance = search_relevance_score(query, searchable)
        if query and not search_relevance_matches(query, searchable):
            continue
        ranked.append((item, score + relevance))
    return sorted(ranked, key=lambda pair: (pair[1], pair[0].updated_at, pair[0].id), reverse=True)


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


def is_current_recallable_memory_item(item: MemoryItem) -> bool:
    return (
        item.status in _CURRENT_RECALL_STATUSES
        and item.removed_at is None
        and item.hidden_at is None
        and item.invalidated_at is None
        and item.valid_to is None
    )


def memory_item_blocks_raw_source_fallback(item: MemoryItem) -> bool:
    return (
        item.status in _RAW_FALLBACK_BLOCKING_STATUSES
        and item.removed_at is None
        and item.hidden_at is None
        and item.invalidated_at is None
        and item.valid_to is None
    )


def is_history_recallable_memory_item(item: MemoryItem) -> bool:
    return is_recallable_memory_item(item, mode="history")


def is_recallable_memory_item(item: MemoryItem, *, mode: str) -> bool:
    if item.removed_at is not None or item.status is MemoryStatus.HIDDEN:
        return False
    if mode == "history":
        return item.status in _HISTORY_RECALL_STATUSES
    return item.status in _CURRENT_RECALL_STATUSES


def memory_item_matches_query(item: MemoryItem, query: str) -> bool:
    return query.casefold() in memory_item_search_text(item).casefold()


def memory_item_search_text(item: MemoryItem) -> str:
    return " ".join(text for text in (item.title, item.content, item.summary) if text is not None)
