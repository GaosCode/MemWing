from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BenchmarkRuntimeBinding:
    runtime: str
    agent_id: str
    workspace_id: str | None
    session_id: str | None


@dataclass(frozen=True, slots=True)
class BenchmarkScope:
    project_memory_space_id: str
    group_id: str | None
    thread_id: str | None
    shared_group_id: str | None


@dataclass(frozen=True, slots=True)
class BenchmarkCleanupResult:
    deleted_counts: dict[str, int]
    prepared: bool


class BenchmarkAdminStorePort(Protocol):
    async def prepare_scope(
        self,
        *,
        scope: BenchmarkScope,
        runtime_binding: BenchmarkRuntimeBinding,
    ) -> None:
        ...

    async def cleanup_scope(
        self,
        *,
        scope: BenchmarkScope,
        runtime_binding: BenchmarkRuntimeBinding,
    ) -> BenchmarkCleanupResult:
        ...
