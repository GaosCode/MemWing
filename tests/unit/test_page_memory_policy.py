from __future__ import annotations

from datetime import UTC, datetime

from memwing.application.page_memory_policy import (
    PageMemoryPolicy,
    PageMemoryPolicyDecision,
    PageMemoryPolicyInput,
)
from memwing.core.models import PageMemory, PageMemoryTopic, SourceEvent


NOW = datetime(2026, 5, 3, tzinfo=UTC)


def test_policy_skips_bootstrap_below_thresholds() -> None:
    result = PageMemoryPolicy().evaluate(
        PageMemoryPolicyInput(
            existing_page=None,
            source_events=tuple(_source_event(f"source_{index}", "short") for index in range(7)),
        )
    )

    assert result.decision == PageMemoryPolicyDecision.SKIP
    assert result.reason == "bootstrap_threshold_not_met"


def test_policy_bootstraps_when_event_threshold_is_met() -> None:
    result = PageMemoryPolicy().evaluate(
        PageMemoryPolicyInput(
            existing_page=None,
            source_events=tuple(_source_event(f"source_{index}", "short") for index in range(8)),
        )
    )

    assert result.decision == PageMemoryPolicyDecision.BOOTSTRAP
    assert result.reason == "bootstrap_event_threshold"


def test_policy_bootstraps_when_token_threshold_is_met() -> None:
    result = PageMemoryPolicy().evaluate(
        PageMemoryPolicyInput(
            existing_page=None,
            source_events=(_source_event("source_001", "token " * 1200),),
        )
    )

    assert result.decision == PageMemoryPolicyDecision.BOOTSTRAP
    assert result.reason == "bootstrap_token_threshold"


def test_policy_rebuilds_only_from_uncovered_source_events() -> None:
    existing_page = _page(source_event_ids=("source_001",))
    result = PageMemoryPolicy(rebuild_min_new_events=2).evaluate(
        PageMemoryPolicyInput(
            existing_page=existing_page,
            source_events=(
                _source_event("source_001", "covered"),
                _source_event("source_002", "new"),
                _source_event("source_003", "new"),
            ),
        )
    )

    assert result.decision == PageMemoryPolicyDecision.REBUILD
    assert result.event_count == 2
    assert result.reason == "rebuild_event_threshold"


def test_policy_forces_rebuild_when_page_needs_rebuild() -> None:
    result = PageMemoryPolicy().evaluate(
        PageMemoryPolicyInput(
            existing_page=_page(needs_rebuild=True),
            source_events=(_source_event("source_001", "covered"),),
        )
    )

    assert result.decision == PageMemoryPolicyDecision.REBUILD
    assert result.reason == "needs_rebuild"


def _source_event(source_event_id: str, content: str) -> SourceEvent:
    return SourceEvent(
        id=source_event_id,
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        author_id=None,
        author_name=None,
        source_type="text",
        content=content,
        content_preview=content[:240],
        source_url=None,
        event_time=NOW,
        raw_payload_hash=f"hash_{source_event_id}",
        metadata={},
        purged_at=None,
        purged_by=None,
        purge_reason=None,
        purge_level="none",
        graph_backend_raw_retained=False,
        created_at=NOW,
    )


def _page(
    *,
    source_event_ids: tuple[str, ...] = ("source_001",),
    needs_rebuild: bool = False,
) -> PageMemory:
    return PageMemory(
        id="page_001",
        project_memory_space_id="project_001",
        group_id="group_001",
        thread_id="thread_001",
        shared_group_id=None,
        scope_type="thread",
        scope_id="thread_001",
        title="Existing",
        brief="Existing brief",
        topics=(
            PageMemoryTopic(
                title="Topic",
                summary="Summary",
                source_event_ids=source_event_ids,
                linked_memory_item_ids=(),
            ),
        ),
        open_questions=(),
        next_steps=(),
        source_event_ids=source_event_ids,
        linked_memory_item_ids=(),
        version=1,
        needs_rebuild=needs_rebuild,
        created_at=NOW,
        updated_at=NOW,
    )
