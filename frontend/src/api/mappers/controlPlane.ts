import type { ControlJobDto, ControlMaintenanceDto, ControlPushCandidateDto } from "../generated/controlPlane";
import type { MaintenanceItem } from "../../shared/types/entities";

export function controlMaintenanceToItems(dto: ControlMaintenanceDto): MaintenanceItem[] {
  return [
    ...dto.jobs.map(jobToMaintenanceItem),
    ...dto.push_candidates.map(pushCandidateToMaintenanceItem),
  ];
}

function jobToMaintenanceItem(job: ControlJobDto): MaintenanceItem {
  const failed = job.status === "dead_letter" || job.dead_letter_reason !== null;
  return {
    id: job.id,
    actionKind: "job",
    jobKind: job.kind,
    retryable: job.retryable,
    type: failed ? "Failed" : "Job",
    title: `${job.kind} · ${job.id}`,
    source: job.kind,
    reason: job.dead_letter_reason ?? job.last_error ?? `${job.attempts}/${job.max_attempts} attempts`,
    state: failed ? "Failed" : "Open",
    updated: job.next_run_at,
    severity: failed ? "failed" : "healthy",
  };
}

function pushCandidateToMaintenanceItem(candidate: ControlPushCandidateDto): MaintenanceItem {
  return {
    id: candidate.id,
    actionKind: "push_candidate",
    sourceEventIds: [...candidate.source_event_ids],
    memoryItemIds: [...candidate.memory_item_ids],
    type: "Push",
    title: candidate.title,
    source: candidate.type,
    reason: candidate.trigger_reason,
    state: candidate.status === "pending" ? "Open" : "Review Pending",
    updated: candidate.created_at,
    severity: candidate.status === "pending" ? "healthy" : "warning",
  };
}
