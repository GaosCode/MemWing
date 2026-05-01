from __future__ import annotations

from datetime import datetime

from memwing.core.models import MemoryItem


SECONDS_PER_DAY = 86_400


def effective_last_touched_at(item: MemoryItem) -> datetime:
    return (
        item.last_confirmed_at
        or item.last_reviewed_at
        or item.activated_at
        or item.created_at
    )


def compute_decayed_score(
    *,
    original_score: float,
    effective_last_touched_at: datetime,
    now: datetime,
    half_life_days: int,
) -> float:
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")

    age_seconds = max(0.0, (now - effective_last_touched_at).total_seconds())
    age_days = age_seconds / SECONDS_PER_DAY
    return original_score * (0.5 ** (age_days / half_life_days))


def should_enter_forgetting_review(
    *,
    decayed_score: float,
    threshold: float,
    pinned: bool,
) -> bool:
    return not pinned and decayed_score < threshold
