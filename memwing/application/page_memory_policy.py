from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from memwing.core.models import PageMemory, SourceEvent


DEFAULT_PAGE_MEMORY_BOOTSTRAP_MIN_EVENTS = 8
DEFAULT_PAGE_MEMORY_BOOTSTRAP_MIN_TOKENS = 1200
DEFAULT_PAGE_MEMORY_REBUILD_MIN_NEW_EVENTS = 8
DEFAULT_PAGE_MEMORY_REBUILD_MIN_NEW_TOKENS = 1200


class PageMemoryPolicyDecision(StrEnum):
    SKIP = "skip"
    BOOTSTRAP = "bootstrap"
    REBUILD = "rebuild"


@dataclass(frozen=True, slots=True)
class PageMemoryPolicyInput:
    existing_page: PageMemory | None
    source_events: tuple[SourceEvent, ...]


@dataclass(frozen=True, slots=True)
class PageMemoryPolicyResult:
    decision: PageMemoryPolicyDecision
    event_count: int
    token_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class PageMemoryPolicy:
    bootstrap_min_events: int = DEFAULT_PAGE_MEMORY_BOOTSTRAP_MIN_EVENTS
    bootstrap_min_tokens: int = DEFAULT_PAGE_MEMORY_BOOTSTRAP_MIN_TOKENS
    rebuild_min_new_events: int = DEFAULT_PAGE_MEMORY_REBUILD_MIN_NEW_EVENTS
    rebuild_min_new_tokens: int = DEFAULT_PAGE_MEMORY_REBUILD_MIN_NEW_TOKENS

    def evaluate(self, policy_input: PageMemoryPolicyInput) -> PageMemoryPolicyResult:
        existing_page = policy_input.existing_page
        if existing_page is not None and existing_page.needs_rebuild:
            return PageMemoryPolicyResult(
                decision=PageMemoryPolicyDecision.REBUILD,
                event_count=0,
                token_count=0,
                reason="needs_rebuild",
            )

        uncovered_events = _uncovered_source_events(
            existing_page=existing_page,
            source_events=policy_input.source_events,
        )
        event_count = len(uncovered_events)
        token_count = sum(estimate_source_event_tokens(event) for event in uncovered_events)

        if existing_page is None:
            if event_count >= self.bootstrap_min_events:
                return PageMemoryPolicyResult(
                    decision=PageMemoryPolicyDecision.BOOTSTRAP,
                    event_count=event_count,
                    token_count=token_count,
                    reason="bootstrap_event_threshold",
                )
            if token_count >= self.bootstrap_min_tokens:
                return PageMemoryPolicyResult(
                    decision=PageMemoryPolicyDecision.BOOTSTRAP,
                    event_count=event_count,
                    token_count=token_count,
                    reason="bootstrap_token_threshold",
                )
            return PageMemoryPolicyResult(
                decision=PageMemoryPolicyDecision.SKIP,
                event_count=event_count,
                token_count=token_count,
                reason="bootstrap_threshold_not_met",
            )

        if event_count >= self.rebuild_min_new_events:
            return PageMemoryPolicyResult(
                decision=PageMemoryPolicyDecision.REBUILD,
                event_count=event_count,
                token_count=token_count,
                reason="rebuild_event_threshold",
            )
        if token_count >= self.rebuild_min_new_tokens:
            return PageMemoryPolicyResult(
                decision=PageMemoryPolicyDecision.REBUILD,
                event_count=event_count,
                token_count=token_count,
                reason="rebuild_token_threshold",
            )
        return PageMemoryPolicyResult(
            decision=PageMemoryPolicyDecision.SKIP,
            event_count=event_count,
            token_count=token_count,
            reason="rebuild_threshold_not_met",
        )


def estimate_source_event_tokens(source_event: SourceEvent) -> int:
    return max(1, len(source_event.content.split()))


def _uncovered_source_events(
    *,
    existing_page: PageMemory | None,
    source_events: tuple[SourceEvent, ...],
) -> tuple[SourceEvent, ...]:
    if existing_page is None:
        return source_events
    covered_source_event_ids = set(existing_page.source_event_ids)
    return tuple(event for event in source_events if event.id not in covered_source_event_ids)
