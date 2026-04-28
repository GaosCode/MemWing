from __future__ import annotations

from enum import StrEnum

from memwing.core.errors import DomainRuleViolation
from memwing.core.models import MemoryStatus


class LifecycleAction(StrEnum):
    APPROVE = "approve"
    ARCHIVE = "archive"
    CONFIRM = "confirm"
    HIDE = "hide"
    INVALIDATE = "invalidate"
    MARK_NEEDS_REVIEW = "mark_needs_review"
    PIN = "pin"
    REMOVE = "remove"
    REVIEW = "review"
    UNARCHIVE = "unarchive"
    UNHIDE = "unhide"
    UNPIN = "unpin"


_RULE_TRANSITIONS: dict[tuple[MemoryStatus, LifecycleAction], MemoryStatus] = {
    (MemoryStatus.CANDIDATE, LifecycleAction.APPROVE): MemoryStatus.ACTIVE,
    (MemoryStatus.CANDIDATE, LifecycleAction.CONFIRM): MemoryStatus.ACTIVE,
    (MemoryStatus.CANDIDATE, LifecycleAction.ARCHIVE): MemoryStatus.ARCHIVED,
    (MemoryStatus.CANDIDATE, LifecycleAction.HIDE): MemoryStatus.HIDDEN,
    (MemoryStatus.CANDIDATE, LifecycleAction.REMOVE): MemoryStatus.REMOVED,
    (MemoryStatus.ACTIVE, LifecycleAction.ARCHIVE): MemoryStatus.ARCHIVED,
    (MemoryStatus.ACTIVE, LifecycleAction.HIDE): MemoryStatus.HIDDEN,
    (MemoryStatus.ACTIVE, LifecycleAction.INVALIDATE): MemoryStatus.INVALID,
    (MemoryStatus.ACTIVE, LifecycleAction.MARK_NEEDS_REVIEW): MemoryStatus.NEEDS_REVIEW,
    (MemoryStatus.ACTIVE, LifecycleAction.REMOVE): MemoryStatus.REMOVED,
    (MemoryStatus.FADING, LifecycleAction.REVIEW): MemoryStatus.ACTIVE,
    (MemoryStatus.FADING, LifecycleAction.CONFIRM): MemoryStatus.ACTIVE,
    (MemoryStatus.FADING, LifecycleAction.ARCHIVE): MemoryStatus.ARCHIVED,
    (MemoryStatus.FADING, LifecycleAction.HIDE): MemoryStatus.HIDDEN,
    (MemoryStatus.FADING, LifecycleAction.MARK_NEEDS_REVIEW): MemoryStatus.NEEDS_REVIEW,
    (MemoryStatus.FADING, LifecycleAction.REMOVE): MemoryStatus.REMOVED,
    (MemoryStatus.NEEDS_REVIEW, LifecycleAction.CONFIRM): MemoryStatus.ACTIVE,
    (MemoryStatus.NEEDS_REVIEW, LifecycleAction.ARCHIVE): MemoryStatus.ARCHIVED,
    (MemoryStatus.NEEDS_REVIEW, LifecycleAction.HIDE): MemoryStatus.HIDDEN,
    (MemoryStatus.NEEDS_REVIEW, LifecycleAction.REMOVE): MemoryStatus.REMOVED,
    (MemoryStatus.ARCHIVED, LifecycleAction.UNARCHIVE): MemoryStatus.ACTIVE,
    (MemoryStatus.ARCHIVED, LifecycleAction.REMOVE): MemoryStatus.REMOVED,
    (MemoryStatus.HIDDEN, LifecycleAction.UNHIDE): MemoryStatus.ACTIVE,
    (MemoryStatus.HIDDEN, LifecycleAction.REMOVE): MemoryStatus.REMOVED,
    (MemoryStatus.INVALID, LifecycleAction.MARK_NEEDS_REVIEW): MemoryStatus.NEEDS_REVIEW,
    (MemoryStatus.INVALID, LifecycleAction.REMOVE): MemoryStatus.REMOVED,
}

_PIN_TRANSITIONS = {
    (status, action): status
    for status in MemoryStatus
    if status is not MemoryStatus.REMOVED
    for action in (LifecycleAction.PIN, LifecycleAction.UNPIN)
}

LIFECYCLE_TRANSITIONS: dict[tuple[MemoryStatus, LifecycleAction], MemoryStatus] = {
    **_RULE_TRANSITIONS,
    **_PIN_TRANSITIONS,
}


def transition_status(current: MemoryStatus, action: LifecycleAction) -> MemoryStatus:
    if current is MemoryStatus.REMOVED:
        raise DomainRuleViolation("removed memories are terminal")

    try:
        return LIFECYCLE_TRANSITIONS[(current, action)]
    except KeyError as exc:
        raise DomainRuleViolation(f"{action.value} is not allowed from {current.value}") from exc
