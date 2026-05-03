from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from memwing.core.models import GraphWriteJob, OutboxJob
from memwing.core.pipeline_readiness import JobStatusCount, OutboxReadiness


def outbox_readiness(jobs: tuple[OutboxJob, ...], *, now: datetime) -> OutboxReadiness:
    by_job_type: dict[str, JobStatusCount] = {}
    grouped: defaultdict[str, list[OutboxJob]] = defaultdict(list)
    for job in jobs:
        grouped[job.job_type].append(job)
    for job_type, grouped_jobs in grouped.items():
        by_job_type[job_type] = job_count(grouped_jobs, now=now)
    total = _sum_job_counts(by_job_type.values())
    return OutboxReadiness(
        pending=total.pending,
        processing_active=total.processing_active,
        processing_stale=total.processing_stale,
        processing_invalid=total.processing_invalid,
        dead_letter=total.dead_letter,
        by_job_type=by_job_type,
    )


def job_count(jobs: Iterable[OutboxJob | GraphWriteJob], *, now: datetime) -> JobStatusCount:
    pending = 0
    processing_active = 0
    processing_stale = 0
    processing_invalid = 0
    dead_letter = 0
    succeeded = 0
    for job in jobs:
        if job.status in ("pending", "retry"):
            pending += 1
        elif job.status == "processing":
            if job.lock_expires_at is None:
                processing_invalid += 1
            elif job.lock_expires_at <= now:
                processing_stale += 1
            else:
                processing_active += 1
        elif job.status == "dead_letter":
            dead_letter += 1
        elif job.status == "succeeded":
            succeeded += 1
    return JobStatusCount(
        pending=pending,
        processing_active=processing_active,
        processing_stale=processing_stale,
        processing_invalid=processing_invalid,
        dead_letter=dead_letter,
        succeeded=succeeded,
    )


def _sum_job_counts(counts: Iterable[JobStatusCount]) -> JobStatusCount:
    total = JobStatusCount()
    for count in counts:
        total = JobStatusCount(
            pending=total.pending + count.pending,
            processing_active=total.processing_active + count.processing_active,
            processing_stale=total.processing_stale + count.processing_stale,
            processing_invalid=total.processing_invalid + count.processing_invalid,
            dead_letter=total.dead_letter + count.dead_letter,
            succeeded=total.succeeded + count.succeeded,
        )
    return total
