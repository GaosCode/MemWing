from __future__ import annotations

from pathlib import Path
from typing import Any

from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.openclaw_feishu import _new_feishu_cli
from memwing_benchmark.openclaw_idempotency import make_idempotency_key
from memwing_benchmark.openclaw_live_runs import (
    _build_seed_flush_commit_text,
    _build_seed_flush_text,
    _message_text,
    _poll_durable_memory,
    _run_live,
)
from memwing_benchmark.openclaw_memory_artifacts import (
    MemoryArtifactPollResult,
    MemoryArtifactSnapshot,
    _diff_memory_artifacts,
    _memory_artifact_contexts,
    _poll_memory_artifact_change,
    _snapshot_as_changed_files,
    _snapshot_memory_artifacts,
    _snapshot_raw,
)
from memwing_benchmark.openclaw_offline_runs import _run_offline, _run_offline_batch
from memwing_benchmark.openclaw_write_runs import (
    _run_write_evaluate_batch,
    _run_write_ingest_batch,
    _run_write_live_batch,
)


__all__ = [
    "MemoryArtifactPollResult",
    "MemoryArtifactSnapshot",
    "_build_seed_flush_commit_text",
    "_build_seed_flush_text",
    "_diff_memory_artifacts",
    "_memory_artifact_contexts",
    "_message_text",
    "_new_feishu_cli",
    "_poll_durable_memory",
    "_poll_memory_artifact_change",
    "_require_openclaw_plugin_tool_evidence",
    "_run_live",
    "_run_offline",
    "_run_offline_batch",
    "_run_write_evaluate_batch",
    "_run_write_ingest_batch",
    "_run_write_live_batch",
    "_snapshot_as_changed_files",
    "_snapshot_memory_artifacts",
    "_snapshot_raw",
    "make_idempotency_key",
]


def _require_openclaw_plugin_tool_evidence(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
) -> None:
    trajectory_dir = Path(config.openclaw.trajectory_dir) if config.openclaw.trajectory_dir else None
    evidence = adapter.collect_memwing_plugin_evidence(trajectory_dir=trajectory_dir)
    raw_records["openclaw_plugin_tool_evidence"] = evidence
    if not evidence:
        raise BenchmarkError("OpenClaw plugin MemWing tool evidence is unavailable")
