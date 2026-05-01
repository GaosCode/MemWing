from datetime import UTC, datetime
from dataclasses import replace

import pytest

from memwing.application.page_memory_rebuild import (
    GuardedPageMemorySynthesis,
    PageMemoryRebuildCommand,
    PageMemoryRebuildPlan,
    PageMemorySynthesisGuard,
    PageMemorySynthesisValidationError,
)
from memwing.core.models import PageMemorySynthesis, PageMemoryTopic
from memwing.core.scope import EffectiveScope
from tests.integration.test_page_memory_service_validation import _source_event


NOW = datetime(2026, 5, 1, tzinfo=UTC)


def test_guard_rejects_redacted_source_events_before_commit() -> None:
    plan = _plan(
        source_events=(
            replace(
                _source_event("source_001", "redacted content", event_time=NOW),
                purged_at=NOW,
                purge_level="memwing_redaction",
            ),
        )
    )

    with pytest.raises(PageMemorySynthesisValidationError):
        PageMemorySynthesisGuard().validate(plan=plan, synthesis=_synthesis())


def test_preview_uses_same_guarded_synthesis_result_as_commit_path() -> None:
    guarded = PageMemorySynthesisGuard().validate(plan=_plan(), synthesis=_synthesis())

    assert isinstance(guarded, GuardedPageMemorySynthesis)
    assert guarded.preview().title == guarded.synthesis.title
    assert guarded.preview().source_event_ids == guarded.synthesis.source_event_ids


def _plan(
    *,
    source_events=None,
) -> PageMemoryRebuildPlan:
    events = source_events or (_source_event("source_001", "source content", event_time=NOW),)
    return PageMemoryRebuildPlan(
        command=PageMemoryRebuildCommand(
            scope=EffectiveScope(
                project_memory_space_id="project_001",
                group_ids=("group_001",),
                thread_id="thread_001",
                shared_group_id=None,
                safe_mode_enabled=False,
                cross_group_allowed=True,
            ),
            scope_type="thread",
            scope_id="thread_001",
            actor_id="user_001",
            reason="manual_rebuild",
            trace_id="trace_page_rebuild",
        ),
        existing_page=None,
        source_events=events,
        linked_memory_items=(),
        rebuild_reason="manual_rebuild",
    )


def _synthesis() -> PageMemorySynthesis:
    return PageMemorySynthesis(
        title="Page preview",
        brief="Preview and commit share this guarded synthesis.",
        topics=(
            PageMemoryTopic(
                title="Preview",
                summary="The guarded output is preview-shaped.",
                source_event_ids=("source_001",),
                linked_memory_item_ids=(),
            ),
        ),
        open_questions=(),
        next_steps=(),
        source_event_ids=("source_001",),
        linked_memory_item_ids=(),
    )
