from __future__ import annotations

from dataclasses import dataclass
from difflib import ndiff
from pathlib import Path
import time
from typing import Any

from memwing_benchmark.schema import utc_now_iso


@dataclass(frozen=True)
class MemoryArtifactSnapshot:
    workspace: Path
    files: dict[str, str]
    captured_at: str

@dataclass(frozen=True)
class MemoryArtifactPollResult:
    before: MemoryArtifactSnapshot
    after: MemoryArtifactSnapshot
    changed_files: list[dict[str, Any]]
    first_changed_at: str | None
    timeout: bool

def _poll_memory_artifact_change(
    *,
    workspace: Path,
    before: MemoryArtifactSnapshot,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> MemoryArtifactPollResult:
    deadline = time.monotonic() + timeout_seconds
    last_after = _snapshot_memory_artifacts(workspace)
    last_changed = _diff_memory_artifacts(before, last_after)
    while True:
        if last_changed:
            return MemoryArtifactPollResult(
                before=before,
                after=last_after,
                changed_files=last_changed,
                first_changed_at=last_after.captured_at,
                timeout=False,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return MemoryArtifactPollResult(
                before=before,
                after=last_after,
                changed_files=last_changed,
                first_changed_at=None,
                timeout=True,
            )
        time.sleep(min(poll_interval_seconds, remaining))
        last_after = _snapshot_memory_artifacts(workspace)
        last_changed = _diff_memory_artifacts(before, last_after)

def _snapshot_memory_artifacts(workspace: Path) -> MemoryArtifactSnapshot:
    files: dict[str, str] = {}
    candidates: list[Path] = []
    for name in ("MEMORY.md", "DREAMS.md"):
        candidates.append(workspace / name)
    memory_dir = workspace / "memory"
    if memory_dir.exists():
        candidates.extend(path for path in memory_dir.rglob("*.md") if path.is_file())
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        try:
            rel_path = path.relative_to(workspace).as_posix()
            files[rel_path] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return MemoryArtifactSnapshot(workspace=workspace, files=files, captured_at=utc_now_iso())

def _diff_memory_artifacts(
    before: MemoryArtifactSnapshot, after: MemoryArtifactSnapshot
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    paths = sorted(set(before.files) | set(after.files))
    for rel_path in paths:
        before_text = before.files.get(rel_path, "")
        after_text = after.files.get(rel_path, "")
        if before_text == after_text:
            continue
        added_lines = [
            line[2:]
            for line in ndiff(before_text.splitlines(), after_text.splitlines())
            if line.startswith("+ ")
        ]
        changed.append(
            {
                "path": rel_path,
                "before_bytes": len(before_text.encode("utf-8")),
                "after_bytes": len(after_text.encode("utf-8")),
                "added_line_count": len(added_lines),
                "added_text": "\n".join(added_lines),
            }
        )
    return changed

def _snapshot_raw(snapshot: MemoryArtifactSnapshot) -> dict[str, Any]:
    return {
        "workspace": str(snapshot.workspace),
        "captured_at": snapshot.captured_at,
        "files": {
            path: {"bytes": len(text.encode("utf-8")), "lines": len(text.splitlines())}
            for path, text in snapshot.files.items()
        },
    }

def _memory_artifact_contexts(snapshot: MemoryArtifactSnapshot) -> list[str]:
    contexts: list[str] = []
    for rel_path, text in sorted(snapshot.files.items()):
        stripped = text.strip()
        if not stripped:
            continue
        contexts.append(f"Source: {rel_path}\n{stripped}")
    return contexts

def _snapshot_as_changed_files(snapshot: MemoryArtifactSnapshot) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for rel_path, text in sorted(snapshot.files.items()):
        if not text.strip():
            continue
        files.append(
            {
                "path": rel_path,
                "before_bytes": 0,
                "after_bytes": len(text.encode("utf-8")),
                "added_line_count": len(text.splitlines()),
                "added_text": text,
                "source": "current_workspace_snapshot",
            }
        )
    return files
