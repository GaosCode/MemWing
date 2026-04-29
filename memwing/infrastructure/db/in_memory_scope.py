from __future__ import annotations

from memwing.core.scope import EffectiveScope


def effective_scope_matches(
    *,
    group_id: str | None,
    thread_id: str | None,
    shared_group_id: str | None,
    scope: EffectiveScope,
) -> bool:
    if scope.group_ids is not None and group_id not in scope.group_ids:
        return False
    if scope.thread_id is not None and thread_id != scope.thread_id:
        return False
    if scope.shared_group_id is not None and shared_group_id != scope.shared_group_id:
        return False
    return True
