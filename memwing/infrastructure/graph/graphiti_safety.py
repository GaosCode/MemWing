from __future__ import annotations

from datetime import datetime
from hashlib import sha1
from pathlib import Path
import re
import sys
from time import perf_counter
import uuid

from memwing.ports.graph_backend import GraphWriteBatchItemResult, GraphWriteBatchResult, GraphWriteRequest

def _blocked_batch_results(
    requests: tuple[GraphWriteRequest, ...],
    *,
    error_type: str,
    first_reason: str,
    blocked_reason: str,
) -> GraphWriteBatchResult:
    items: list[GraphWriteBatchItemResult] = []
    for index, request in enumerate(requests):
        items.append(
            GraphWriteBatchItemResult(
                job_id=request.job.id,
                result=None,
                error_type=error_type if index == 0 else "GraphitiOrderedBatchBlocked",
                error_message=None,
                reason_code=first_reason if index == 0 else blocked_reason,
                retryable=True,
            )
        )
    return GraphWriteBatchResult(items=tuple(items))

def _safe_error_message(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    if len(text) > 500:
        return f"{text[:500]}...[truncated]"
    return text

def _graph_write_request_order(request: GraphWriteRequest) -> tuple[datetime, datetime, str]:
    return (
        request.memory_item.event_time or request.source_events[0].event_time,
        request.job.created_at,
        request.job.id,
    )

def _stable_graphiti_episode_uuid(request: GraphWriteRequest) -> str:
    key = "|".join(
        (
            "graphiti",
            request.job.project_memory_space_id,
            request.memory_item.id,
            str(request.memory_item.lifecycle_revision),
            ",".join(request.job.source_event_ids),
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))

def _raw_episode(request: GraphWriteRequest) -> object:
    vendored_parent = Path(__file__).resolve().parent
    if str(vendored_parent) not in sys.path:
        sys.path.insert(0, str(vendored_parent))
    from graphiti_core.nodes import EpisodeType
    from graphiti_core.utils.bulk_utils import RawEpisode

    return RawEpisode(
        name=request.memory_item.title,
        uuid=_stable_graphiti_episode_uuid(request),
        content=request.memory_item.content,
        source_description="MemWing graph write job",
        source=EpisodeType.message,
        reference_time=(
            request.memory_item.event_time
            or request.source_events[0].event_time
            or request.memory_item.created_at
        ),
    )

def _graphiti_group_id(project_memory_space_id: str) -> str:
    if re.fullmatch(r"[a-zA-Z0-9_-]+", project_memory_space_id):
        return project_memory_space_id
    readable = re.sub(r"[^a-zA-Z0-9_-]+", "_", project_memory_space_id).strip("_")
    if not readable:
        readable = "project"
    digest = sha1(project_memory_space_id.encode("utf-8")).hexdigest()[:12]
    return f"mw_{readable[:80]}_{digest}"

def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000
