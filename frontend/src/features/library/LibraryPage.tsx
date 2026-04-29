import { useState } from "react";
import { Check, Clock3, Columns3, ExternalLink, List, ListFilter, Search } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { IconButton, PageHeader, SelectMenu, StatusBadge, StrengthMeter } from "../../shared/components/ui";
import { memoryTypeLabel } from "../../shared/design-system/status";
import type { MemoryItem } from "../../shared/types/entities";

const primaryFilters = ["Project", "Group", "Thread", "Type", "Lifecycle Status"];
const advancedFilters = ["Strength", "Pinned", "Archived", "Hidden", "Needs Review", "Source Platform", "Time"];
const filterOptions: Record<string, string[]> = {
  Project: ["Any", "产品记忆治理", "安全群治理"],
  Group: ["Any", "产品线", "安全群"],
  Thread: ["Any", "自动化维护", "项目记忆重建"],
  Type: ["Any", "Preference", "Decision", "Rule", "Evidence"],
  "Lifecycle Status": ["Any", "Active", "Candidate", "Fading", "Needs Review"],
  Strength: ["Any", "High", "Medium", "Low"],
  Pinned: ["Any", "Pinned only", "Not pinned"],
  Archived: ["Any", "Visible only", "Archived only"],
  Hidden: ["Any", "Visible only", "Hidden only"],
  "Needs Review": ["Any", "Review due", "No review"],
  "Source Platform": ["Any", "Feishu", "Project Memory", "AI 自动化维护"],
  Time: ["Any", "Today", "Last 7 days", "Older"],
};

type LibraryView = "List" | "Timeline" | "Board";
type Density = "Comfortable" | "Compact";

export function LibraryPage({ selected, onSelect }: { selected: MemoryItem; onSelect: (memory: MemoryItem) => void }) {
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [view, setView] = useState<LibraryView>("List");
  const [density, setDensity] = useState<Density>("Comfortable");
  const [sortDescending, setSortDescending] = useState(true);
  const [savedView, setSavedView] = useState("Default");
  const [notice, setNotice] = useState("Ready");
  const [filters, setFilters] = useState<Record<string, string>>({});

  function updateFilter(label: string, next: string) {
    setFilters((currentFilters) => ({ ...currentFilters, [label]: next }));
    setNotice(`${label}: ${next}`);
  }

  function clearFilters() {
    setFilters({});
    setNotice("Filters cleared");
  }

  const visibleMemories = [...memories].sort((a, b) =>
    sortDescending ? b.lastSeen.localeCompare(a.lastSeen) : a.lastSeen.localeCompare(b.lastSeen),
  );

  return (
    <>
      <PageHeader
        title="Memory Library"
        subtitle="Search, inspect, and manage long-term memory across lifecycle states."
        actions={
          <div className="segmented">
            {[
              { label: "List" as const, icon: List },
              { label: "Timeline" as const, icon: Clock3 },
              { label: "Board" as const, icon: Columns3 },
            ].map(({ label, icon: Icon }) => (
              <button key={label} className={view === label ? "is-active" : ""} type="button" onClick={() => setView(label)}>
                <Icon size={18} />
                {label}
              </button>
            ))}
          </div>
        }
      />

      <div className={`filter-grid ${filtersExpanded ? "is-expanded" : ""}`} aria-label="Library filters">
        {primaryFilters.map((label) => (
          <FilterControl key={label} label={label} value={filters[label] ?? "Any"} onChange={(next) => updateFilter(label, next)} />
        ))}
        <button
          className="secondary-button filter-action filter-toggle"
          type="button"
          aria-expanded={filtersExpanded}
          onClick={() => setFiltersExpanded((isExpanded) => !isExpanded)}
        >
          <ListFilter size={17} />
          {filtersExpanded ? "Less Filters" : "More Filters"}
        </button>
        {filtersExpanded ? (
          <>
            {advancedFilters.map((label) => (
              <FilterControl key={label} label={label} value={filters[label] ?? "Any"} onChange={(next) => updateFilter(label, next)} />
            ))}
            <label className="filter-search">
              <Search size={17} />
              <input placeholder="搜索记忆、来源、标签、ID..." onChange={(event) => setNotice(`Search scoped to "${event.target.value}"`)} />
              <kbd>⌘ K</kbd>
            </label>
            <button className="secondary-button filter-action" type="button" onClick={clearFilters}>Clear All</button>
          </>
        ) : null}
      </div>

      <div className="table-toolbar">
        <div>
          <h2>All Memories</h2>
          <span>248 results</span>
        </div>
        <div className="toolbar-actions">
          <SelectMenu
            className="toolbar-select"
            label="Sort"
            value={`Last Seen (${sortDescending ? "desc" : "asc"})`}
            options={["Last Seen (desc)", "Last Seen (asc)"]}
            onChange={(next) => {
              setSortDescending(next.includes("desc"));
              setNotice(`Sorted by ${next}`);
            }}
          />
          <SelectMenu
            className="toolbar-select"
            label="Density"
            value={density}
            options={["Comfortable", "Compact"]}
            onChange={(next) => {
              setDensity(next as Density);
              setNotice(`Density set to ${next}`);
            }}
          />
          <button type="button" onClick={() => setNotice("Export queued as CSV")}>
            <ExternalLink size={16} />
            Export
          </button>
          <SelectMenu
            className="toolbar-select"
            label="Saved Views"
            value={savedView}
            options={["Default", "Review Due", "Pinned", "Fading"]}
            onChange={(next) => {
              setSavedView(next);
              setNotice(`Saved view switched to ${next}`);
            }}
          />
        </div>
      </div>

      <div className="notice-row"><Check size={15} />{notice}</div>

      {view === "List" ? (
        <MemoryListView memories={visibleMemories} density={density} selected={selected} onSelect={onSelect} />
      ) : null}
      {view === "Timeline" ? (
        <MemoryTimelineView memories={visibleMemories} selected={selected} onSelect={onSelect} />
      ) : null}
      {view === "Board" ? (
        <MemoryBoardView memories={visibleMemories} selected={selected} onSelect={onSelect} />
      ) : null}
    </>
  );
}

function FilterControl({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="filter-control">
      <span>{label}</span>
      <SelectMenu className="filter-select" value={value} options={filterOptions[label] ?? ["Any"]} onChange={onChange} />
    </label>
  );
}

function MemoryListView({
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
  return (
    <div className={`memory-table memory-table--${density.toLowerCase()}`} role="table" aria-label="Memory table">
      <div className="table-row table-row--head" role="row">
        <span><input type="checkbox" aria-label="Select all memories" /></span>
        <span>Title</span>
        <span>Type</span>
        <span>Source</span>
        <span>Last Seen</span>
        <span>Status</span>
        <span>Strength</span>
        <span>Tags / Flags</span>
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
          <span>{memoryTypeLabel[memory.type]}</span>
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

function MemoryTimelineView({
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

function MemoryBoardView({
  memories,
  selected,
  onSelect,
}: {
  memories: MemoryItem[];
  selected: MemoryItem;
  onSelect: (memory: MemoryItem) => void;
}) {
  const groups = [
    ["Active", memories.filter((memory) => memory.status === "active")],
    ["Review", memories.filter((memory) => memory.status === "candidate" || memory.status === "needs_review")],
    ["Fading", memories.filter((memory) => memory.status === "fading" || memory.status === "hidden" || memory.status === "invalid")],
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
