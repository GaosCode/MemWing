import type { MemoryListItemDto } from "../generated/memoryList";
import type { MemoryItem } from "../../shared/types/entities";

export function memoryListItemToViewModel(dto: MemoryListItemDto): MemoryItem {
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
  };
}
