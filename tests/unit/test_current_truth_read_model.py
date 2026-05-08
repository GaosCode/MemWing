from datetime import UTC, datetime

from memwing.application.current_truth import (
    CurrentTruthBranchTiming,
    CurrentTruthResult,
    CurrentTruthWarning,
)
from memwing.application.current_truth_read_model import current_truth_to_access_result
from memwing.core.memory_search import MemorySearchResultItem


NOW = datetime(2026, 5, 6, tzinfo=UTC)


def test_current_truth_read_model_keeps_authority_order_and_page_memory_background() -> None:
    result = current_truth_to_access_result(
        _current_truth(
            current_facts=(_item("memory_001", "memory_item", "Current fact", score=0.8),),
            background=(_item("page_001", "page_memory", "Background", score=None),),
            supporting_evidence=(_item("evidence_001", "evidence_index", "Evidence", score=0.9),),
        ),
        limit=10,
    )

    assert tuple(item.id for item in result.results) == (
        "memory_001",
        "page_001",
        "evidence_001",
    )


def test_current_truth_read_model_uses_raw_events_only_as_last_resort() -> None:
    result = current_truth_to_access_result(
        _current_truth(
            current_facts=(),
            background=(),
            supporting_evidence=(),
            raw_events=(_item("source_001", "source_event", "Raw event", score=None),),
        ),
        limit=10,
    )

    assert tuple(item.id for item in result.results) == ("source_001",)


def test_current_truth_read_model_paginates_and_passes_warnings_and_diagnostics() -> None:
    result = current_truth_to_access_result(
        _current_truth(
            current_facts=(
                _item("memory_001", "memory_item", "One", score=0.8),
                _item("memory_002", "memory_item", "Two", score=0.7),
            ),
            warnings=(
                CurrentTruthWarning(
                    branch="graph_backend",
                    reason_code="timeout",
                    message="Graph timed out.",
                ),
            ),
        ),
        limit=1,
    )

    assert tuple(item.id for item in result.results) == ("memory_001",)
    assert result.next_cursor == "offset:1"
    assert result.warnings == (
        {
            "branch": "graph_backend",
            "reason_code": "timeout",
            "message": "Graph timed out.",
        },
    )
    assert result.diagnostics["current_truth"]["branch_timings"][0]["branch"] == "graph_backend"


def test_current_truth_read_model_relevance_sort_can_prepend_assembled_context() -> None:
    result = current_truth_to_access_result(
        _current_truth(
            current_facts=(
                _item("memory_owner", "memory_item", "云帆负责人是沈南。", score=0.6),
                _item("memory_deadline", "memory_item", "云帆上线窗口是 5 月 20 日。", score=0.6),
            ),
        ),
        limit=10,
        sort="relevance",
        query="云帆负责人是谁？上线窗口是什么？",
    )

    assert result.results[0].id == "current_truth:assembled"
    assert result.results[0].metadata["assembled_item_ids"] == (
        "memory_owner",
        "memory_deadline",
    )


def _current_truth(
    *,
    current_facts: tuple[MemorySearchResultItem, ...] = (),
    background: tuple[MemorySearchResultItem, ...] = (),
    supporting_evidence: tuple[MemorySearchResultItem, ...] = (),
    raw_events: tuple[MemorySearchResultItem, ...] = (),
    warnings: tuple[CurrentTruthWarning, ...] = (),
) -> CurrentTruthResult:
    return CurrentTruthResult(
        working_memory=(),
        current_facts=current_facts,
        background=background,
        supporting_evidence=supporting_evidence,
        raw_events=raw_events,
        warnings=warnings,
        branch_timings=(
            CurrentTruthBranchTiming(
                branch="graph_backend",
                latency_ms=12,
                result_count=0,
                status="ok",
            ),
        ),
        trace_id="trace_current",
    )


def _item(
    item_id: str,
    source: str,
    text: str,
    *,
    score: float | None,
) -> MemorySearchResultItem:
    return MemorySearchResultItem(
        id=item_id,
        text=text,
        score=score,
        source=source,
        source_event_ids=("source_001",),
        memory_item_ids=(item_id,) if source == "memory_item" else (),
        valid_from=NOW,
        valid_to=None,
        metadata={},
    )
