from __future__ import annotations

from statistics import mean


def average_latency_ms(values: list[int]) -> float | None:
    if not values:
        return None
    return mean(values)
