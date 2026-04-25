from __future__ import annotations


def answer_accuracy(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)
