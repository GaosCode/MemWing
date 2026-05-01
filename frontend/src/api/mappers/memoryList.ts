import type { MemoryListItemDto } from "../generated/memoryList";
import type { MemoryItem } from "../../shared/types/entities";

export function memoryListItemToViewModel(dto: MemoryListItemDto): MemoryItem {
  return {
    id: dto.id,
    title: dto.title,
    type: dto.display_type,
    source: formatSource(dto),
    lastSeen: dto.updated_at,
    status: dto.status,
    strength: dto.decay_score,
    flags: [...dto.flags],
    reason: dto.retention_reason,
    forgetting: {
      decayScore: dto.decay_score,
      originalScore: dto.original_score,
      halfLifeDays: dto.half_life_days,
      recallThreshold: dto.recall_threshold,
      lastReinforcedAt: dto.last_reinforced_at,
      nextReviewAt: dto.next_review_at,
      retentionReason: dto.retention_reason,
      curveState: dto.curve_state,
      curvePoints: [],
    },
  };
}

function formatSource(dto: MemoryListItemDto): string {
  const scope = [dto.group_id, dto.thread_id].filter((value): value is string => value !== null);
  if (scope.length === 0) {
    return dto.source_state;
  }
  return `${scope.join(" · ")} · ${dto.source_state}`;
}
