import { StatusBadge, StrengthMeter } from "../../shared/components/ui";
import { memoryTypeLabel } from "../../shared/i18n/formatters";
import { useI18n } from "../../shared/i18n";
import type { MemoryItem } from "../../shared/types/entities";

export type Density = "Comfortable" | "Compact";
export type LibraryView = "List" | "Timeline" | "Board";

export function MemoryListView({
  memories,
  density,
  selected,
  onSelect,
}: {
  memories: MemoryItem[];
  density: Density;
  selected: MemoryItem;
  onSelect: (memory: MemoryItem) => void;
}) {
  const { dictionary } = useI18n();
  return (
    <div className={`memory-table memory-table--${density.toLowerCase()}`} role="table" aria-label={dictionary.library.memoryTableAria}>
      <div className="table-row table-row--head" role="row">
        <span><input type="checkbox" aria-label={dictionary.library.selectAll} /></span>
        <span>{dictionary.library.columns.title}</span>
        <span>{dictionary.library.columns.type}</span>
        <span>{dictionary.library.columns.source}</span>
        <span>{dictionary.library.columns.lastSeen}</span>
        <span>{dictionary.library.columns.status}</span>
        <span>{dictionary.library.columns.strength}</span>
        <span>{dictionary.library.columns.tags}</span>
      </div>
      {memories.map((memory) => (
        <button
          className={`table-row ${selected.id === memory.id ? "is-selected" : ""}`}
          key={memory.id}
          onClick={() => onSelect(memory)}
          role="row"
        >
          <span><input type="checkbox" checked={selected.id === memory.id} readOnly aria-label={`Select ${memory.title}`} /></span>
          <span className="table-title">{memory.title}</span>
          <span>{memoryTypeLabel(dictionary, memory.type)}</span>
          <span>{memory.source}</span>
          <span>{memory.lastSeen.slice(0, 16)}</span>
          <span><StatusBadge status={memory.status} /></span>
          <span><StrengthMeter value={memory.strength} compact /></span>
          <span className="flag-list">{memory.flags.map((flag) => <span key={flag}>{flag}</span>)}</span>
        </button>
      ))}
    </div>
  );
}

export function MemoryTimelineView({
  memories,
  selected,
  onSelect,
}: {
  memories: MemoryItem[];
  selected: MemoryItem;
  onSelect: (memory: MemoryItem) => void;
}) {
  return (
    <div className="timeline-board">
      {memories.map((memory) => (
        <button key={memory.id} className={`timeline-card ${selected.id === memory.id ? "is-selected" : ""}`} type="button" onClick={() => onSelect(memory)}>
          <span>{memory.lastSeen.slice(0, 16)}</span>
          <strong>{memory.title}</strong>
          <p>{memory.reason}</p>
          <StatusBadge status={memory.status} />
        </button>
      ))}
    </div>
  );
}

export function MemoryBoardView({
  memories,
  selected,
  onSelect,
}: {
  memories: MemoryItem[];
  selected: MemoryItem;
  onSelect: (memory: MemoryItem) => void;
}) {
  const { dictionary } = useI18n();
  const groups = [
    [dictionary.library.views.active, memories.filter((memory) => memory.status === "active")],
    [dictionary.library.views.review, memories.filter((memory) => memory.status === "candidate" || memory.status === "needs_review")],
    [dictionary.library.views.fading, memories.filter((memory) => memory.status === "fading" || memory.status === "hidden" || memory.status === "invalid")],
  ] as const;

  return (
    <div className="memory-board">
      {groups.map(([title, group]) => (
        <section key={title} className="board-column">
          <h3>{title}<span>{group.length}</span></h3>
          {group.map((memory) => (
            <button key={memory.id} className={`board-card ${selected.id === memory.id ? "is-selected" : ""}`} type="button" onClick={() => onSelect(memory)}>
              <strong>{memory.title}</strong>
              <p>{memory.source}</p>
              <StrengthMeter value={memory.strength} compact />
            </button>
          ))}
        </section>
      ))}
    </div>
  );
}
