import type { MemoryListItemDto } from "../generated/memoryList";
import type { CurveState, ForgettingCurve, MemoryItem } from "../../shared/types/entities";

export function memoryListItemToViewModel(dto: MemoryListItemDto): MemoryItem {
  const forgetting = deriveForgettingCurve(dto);
  return {
    id: dto.id,
    title: dto.title,
    type: dto.display_type,
    source: dto.source_label,
    lastSeen: dto.last_seen,
    status: dto.status,
    strength: dto.strength,
    flags: [...dto.flags],
    reason: dto.reason,
    forgetting,
  };
}

function deriveForgettingCurve(dto: MemoryListItemDto): ForgettingCurve {
  const curveState = curveStateFor(dto);
  const originalScore = Math.min(0.98, Math.max(dto.strength, dto.strength + 0.14));
  const recallThreshold = dto.status === "hidden" || dto.status === "invalid" ? 0.5 : 0.45;
  const halfLifeDays = dto.status === "fading" || dto.status === "needs_review" ? 14 : 30;
  const decayScore = dto.strength;

  return {
    decayScore,
    originalScore,
    halfLifeDays,
    recallThreshold,
    lastReinforcedAt: dto.last_seen,
    nextReviewAt: nextReviewFor(dto.status),
    retentionReason: retentionReasonFor(dto),
    curveState,
    curvePoints: [0, 7, 14, 21, 30].map((day) => ({
      day,
      score: Number((originalScore * Math.exp((-Math.log(2) / halfLifeDays) * day)).toFixed(2)),
    })),
  };
}

function curveStateFor(dto: MemoryListItemDto): CurveState {
  if (dto.flags.includes("pinned")) {
    return "pinned";
  }
  if (dto.status === "fading") {
    return "fading";
  }
  if (dto.status === "needs_review") {
    return "review_due";
  }
  if (dto.status === "hidden" || dto.status === "invalid" || dto.strength < 0.35) {
    return "ready_to_forget";
  }
  return "stable";
}

function nextReviewFor(status: MemoryListItemDto["status"]): string {
  if (status === "fading" || status === "needs_review") {
    return "2026-04-28 09:00";
  }
  if (status === "hidden" || status === "invalid") {
    return "2026-04-27 18:00";
  }
  return "2026-05-04 09:00";
}

function retentionReasonFor(dto: MemoryListItemDto): string {
  if (dto.flags.includes("pinned")) {
    return "Pinned by reviewer; decay is visible but recall bypass is active.";
  }
  if (dto.status === "fading") {
    return "Low recent reuse; scheduled for review before recall drops below threshold.";
  }
  if (dto.status === "needs_review") {
    return "Superseded wording needs reviewer confirmation before forgetting.";
  }
  if (dto.status === "hidden" || dto.status === "invalid") {
    return "No longer eligible for default recall; safe to archive after audit check.";
  }
  return dto.reason;
}
