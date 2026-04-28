import pytest

from memwing.core.models import MemoryDisplayType, MemoryRoute, MemoryStatus
from memwing.core.scope import EffectiveScope, MemoryScope


def test_memory_scope_does_not_accept_safe_mode_from_requesters() -> None:
    scope = MemoryScope(
        project_memory_space_id="project_001",
        group_id="feishu_group_001",
        thread_id="thread_001",
        shared_group_id=None,
    )

    assert scope.project_memory_space_id == "project_001"
    assert scope.group_id == "feishu_group_001"

    with pytest.raises(TypeError):
        MemoryScope(  # type: ignore[call-arg]
            project_memory_space_id="project_001",
            group_id="feishu_group_001",
            safe_mode_enabled=True,
        )


def test_effective_scope_contains_server_resolved_safe_mode() -> None:
    scope = EffectiveScope(
        project_memory_space_id="project_001",
        group_ids=("feishu_group_001",),
        thread_id="thread_001",
        shared_group_id="shared_001",
        safe_mode_enabled=True,
        cross_group_allowed=False,
    )

    assert scope.safe_mode_enabled is True
    assert scope.cross_group_allowed is False
    assert scope.group_ids == ("feishu_group_001",)


def test_memory_enums_are_centralized_contract_values() -> None:
    assert {item.value for item in MemoryRoute} == {"graph", "vector_only", "raw_only", "manual"}
    assert {item.value for item in MemoryDisplayType} == {
        "decision",
        "task",
        "preference",
        "rule",
        "note",
        "evidence",
    }
    assert {item.value for item in MemoryStatus} == {
        "candidate",
        "active",
        "fading",
        "archived",
        "hidden",
        "invalid",
        "needs_review",
        "removed",
    }
