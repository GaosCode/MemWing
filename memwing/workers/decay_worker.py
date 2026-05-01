from __future__ import annotations

from datetime import datetime
from typing import Final

from memwing.application.decay_service import DecayProcessCommand, DecayProcessResult, DecayService
from memwing.core.models import OutboxJob


DECAY_JOB_TYPE: Final = "memory.decay"


class DecayWorker:
    def __init__(self, decay_service: DecayService) -> None:
        self._decay_service = decay_service

    async def run(self, job: OutboxJob, *, now: datetime) -> DecayProcessResult:
        if job.job_type != DECAY_JOB_TYPE:
            raise ValueError(f"unsupported decay job type: {job.job_type}")
        threshold = job.payload_json.get("threshold", 0.5)
        if not isinstance(threshold, int | float):
            raise ValueError("decay job threshold must be numeric")
        return await self._decay_service.process_project(
            DecayProcessCommand(
                project_memory_space_id=job.project_memory_space_id,
                now=now,
                threshold=float(threshold),
                trace_id=f"decay_worker:{job.id}",
            )
        )
