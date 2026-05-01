from __future__ import annotations

from datetime import datetime, timedelta
import math

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


def time_to_threshold_days(
    *,
    original_score: float,
    effective_last_touched_at: datetime,
    now: datetime,
    half_life_days: int,
    threshold: float,
) -> float:
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    if original_score <= 0 or original_score <= threshold:
        return 0.0

    total_days_to_threshold = half_life_days * math.log(threshold / original_score, 0.5)
    elapsed_days = max(0.0, (now - effective_last_touched_at).total_seconds() / SECONDS_PER_DAY)
    return max(0.0, total_days_to_threshold - elapsed_days)


def next_threshold_at(
    *,
    original_score: float,
    effective_last_touched_at: datetime,
    now: datetime,
    half_life_days: int,
    threshold: float,
) -> datetime:
    remaining_days = time_to_threshold_days(
        original_score=original_score,
        effective_last_touched_at=effective_last_touched_at,
        now=now,
        half_life_days=half_life_days,
        threshold=threshold,
    )
    if remaining_days == 0:
        return now
    return now + timedelta(days=remaining_days)
