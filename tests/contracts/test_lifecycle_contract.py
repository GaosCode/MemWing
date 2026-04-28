import pytest

from memwing.core.errors import DomainRuleViolation
from memwing.core.lifecycle import LIFECYCLE_TRANSITIONS, LifecycleAction, transition_status
from memwing.core.models import MemoryStatus


def test_lifecycle_transition_contract_blocks_removed_terminal_state() -> None:
    assert (
        transition_status(MemoryStatus.CANDIDATE, LifecycleAction.APPROVE)
        is MemoryStatus.ACTIVE
    )
    assert (
        transition_status(MemoryStatus.CANDIDATE, LifecycleAction.CONFIRM)
        is MemoryStatus.ACTIVE
    )
    assert (
        transition_status(MemoryStatus.CANDIDATE, LifecycleAction.ARCHIVE)
        is MemoryStatus.ARCHIVED
    )
    assert transition_status(MemoryStatus.CANDIDATE, LifecycleAction.HIDE) is MemoryStatus.HIDDEN
    assert (
        transition_status(MemoryStatus.CANDIDATE, LifecycleAction.REMOVE)
        is MemoryStatus.REMOVED
    )
    assert transition_status(MemoryStatus.ACTIVE, LifecycleAction.ARCHIVE) is MemoryStatus.ARCHIVED
    assert transition_status(MemoryStatus.ACTIVE, LifecycleAction.HIDE) is MemoryStatus.HIDDEN
    assert (
        transition_status(MemoryStatus.ACTIVE, LifecycleAction.INVALIDATE)
        is MemoryStatus.INVALID
    )
    assert (
        transition_status(MemoryStatus.ACTIVE, LifecycleAction.MARK_NEEDS_REVIEW)
        is MemoryStatus.NEEDS_REVIEW
    )
    assert transition_status(MemoryStatus.ACTIVE, LifecycleAction.REMOVE) is MemoryStatus.REMOVED
    assert transition_status(MemoryStatus.FADING, LifecycleAction.REVIEW) is MemoryStatus.ACTIVE
    assert transition_status(MemoryStatus.FADING, LifecycleAction.CONFIRM) is MemoryStatus.ACTIVE
    assert transition_status(MemoryStatus.FADING, LifecycleAction.ARCHIVE) is MemoryStatus.ARCHIVED
    assert transition_status(MemoryStatus.FADING, LifecycleAction.HIDE) is MemoryStatus.HIDDEN
    assert (
        transition_status(MemoryStatus.FADING, LifecycleAction.MARK_NEEDS_REVIEW)
        is MemoryStatus.NEEDS_REVIEW
    )
    assert transition_status(MemoryStatus.FADING, LifecycleAction.REMOVE) is MemoryStatus.REMOVED
    assert (
        transition_status(MemoryStatus.NEEDS_REVIEW, LifecycleAction.CONFIRM)
        is MemoryStatus.ACTIVE
    )
    assert (
        transition_status(MemoryStatus.NEEDS_REVIEW, LifecycleAction.ARCHIVE)
        is MemoryStatus.ARCHIVED
    )
    assert (
        transition_status(MemoryStatus.NEEDS_REVIEW, LifecycleAction.HIDE)
        is MemoryStatus.HIDDEN
    )
    assert (
        transition_status(MemoryStatus.NEEDS_REVIEW, LifecycleAction.REMOVE)
        is MemoryStatus.REMOVED
    )
    assert (
        transition_status(MemoryStatus.ARCHIVED, LifecycleAction.UNARCHIVE)
        is MemoryStatus.ACTIVE
    )
    assert transition_status(MemoryStatus.ARCHIVED, LifecycleAction.REMOVE) is MemoryStatus.REMOVED
    assert transition_status(MemoryStatus.HIDDEN, LifecycleAction.UNHIDE) is MemoryStatus.ACTIVE
    assert transition_status(MemoryStatus.HIDDEN, LifecycleAction.REMOVE) is MemoryStatus.REMOVED
    assert (
        transition_status(MemoryStatus.INVALID, LifecycleAction.MARK_NEEDS_REVIEW)
        is MemoryStatus.NEEDS_REVIEW
    )
    assert transition_status(MemoryStatus.INVALID, LifecycleAction.REMOVE) is MemoryStatus.REMOVED
    assert transition_status(MemoryStatus.ACTIVE, LifecycleAction.PIN) is MemoryStatus.ACTIVE
    assert transition_status(MemoryStatus.ACTIVE, LifecycleAction.UNPIN) is MemoryStatus.ACTIVE

    with pytest.raises(DomainRuleViolation, match="removed"):
        transition_status(MemoryStatus.REMOVED, LifecycleAction.CONFIRM)


def test_lifecycle_transition_table_matches_rules_document() -> None:
    expected_edges = {
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

    pin_edges = {
        (status, action): status
        for status in MemoryStatus
        if status is not MemoryStatus.REMOVED
        for action in (LifecycleAction.PIN, LifecycleAction.UNPIN)
    }

    assert LIFECYCLE_TRANSITIONS == expected_edges | pin_edges
