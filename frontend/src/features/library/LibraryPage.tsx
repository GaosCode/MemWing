import { useState } from "react";
import { Check, Clock3, Columns3, ExternalLink, List, ListFilter, Search } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { IconButton, PageHeader, SelectMenu, StatusBadge, StrengthMeter } from "../../shared/components/ui";
import { memoryTypeLabel } from "../../shared/i18n/formatters";
import { useI18n } from "../../shared/i18n";
import type { MemoryItem } from "../../shared/types/entities";

const primaryFilters = ["project", "group", "thread", "type", "lifecycle"] as const;
const advancedFilters = ["strength", "pinned", "archived", "hidden", "needsReview", "sourcePlatform", "time"] as const;
type FilterKey = (typeof primaryFilters)[number] | (typeof advancedFilters)[number];

type LibraryView = "List" | "Timeline" | "Board";
type Density = "Comfortable" | "Compact";

export function LibraryPage({ selected, onSelect }: { selected: MemoryItem; onSelect: (memory: MemoryItem) => void }) {
  const { dictionary } = useI18n();
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [view, setView] = useState<LibraryView>("List");
  const [density, setDensity] = useState<Density>("Comfortable");
  const [sortDescending, setSortDescending] = useState(true);
  const [savedView, setSavedView] = useState("Default");
  const [notice, setNotice] = useState(dictionary.library.ready);
  const [filters, setFilters] = useState<Record<string, string>>({});

  function filterLabel(key: FilterKey) {
    return dictionary.library.filterLabels[key];
  }

  function filterOptions(key: FilterKey) {
    const options = dictionary.library.filterOptions;
    const status = dictionary.status.lifecycle;
    if (key === "project") {
      return [options.any, "产品记忆治理", "安全群治理"];
    }
    if (key === "group") {
      return [options.any, "产品线", "安全群"];
    }
    if (key === "thread") {
      return [options.any, "自动化维护", "项目记忆重建"];
    }
    if (key === "type") {
      return [options.any, dictionary.status.memoryType.preference, dictionary.status.memoryType.decision, dictionary.status.memoryType.rule, dictionary.status.memoryType.evidence];
    }
    if (key === "lifecycle") {
      return [options.any, status.active.label, status.candidate.label, status.fading.label, status.needs_review.label];
    }
    if (key === "strength") {
      return [options.any, options.high, options.medium, options.low];
    }
    if (key === "pinned") {
      return [options.any, options.pinnedOnly, options.notPinned];
    }
    if (key === "archived") {
      return [options.any, options.visibleOnly, options.archivedOnly];
    }
    if (key === "hidden") {
      return [options.any, options.visibleOnly, options.hiddenOnly];
    }
    if (key === "needsReview") {
      return [options.any, options.reviewDue, options.noReview];
    }
    if (key === "sourcePlatform") {
      return [options.any, "Feishu", dictionary.app.nav.project, "AI 自动化维护"];
    }
    return [options.any, options.today, options.last7Days, options.older];
  }

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
        title={dictionary.library.title}
        subtitle={dictionary.library.subtitle}
        actions={
          <div className="segmented">
            {[
              { label: "List" as const, icon: List },
              { label: "Timeline" as const, icon: Clock3 },
              { label: "Board" as const, icon: Columns3 },
            ].map(({ label, icon: Icon }) => (
              <button key={label} className={view === label ? "is-active" : ""} type="button" onClick={() => setView(label)}>
                <Icon size={18} />
                {dictionary.library.views[label.toLowerCase() as "list" | "timeline" | "board"]}
              </button>
            ))}
          </div>
        }
      />

      <div className={`filter-grid ${filtersExpanded ? "is-expanded" : ""}`} aria-label={dictionary.library.filtersAria}>
        {primaryFilters.map((key) => (
          <FilterControl key={key} label={filterLabel(key)} value={filters[key] ?? dictionary.library.filterOptions.any} options={filterOptions(key)} onChange={(next) => updateFilter(key, next)} />
        ))}
        <button
          className="secondary-button filter-action filter-toggle"
          type="button"
          aria-expanded={filtersExpanded}
          onClick={() => setFiltersExpanded((isExpanded) => !isExpanded)}
        >
          <ListFilter size={17} />
          {filtersExpanded ? dictionary.actions.lessFilters : dictionary.actions.moreFilters}
        </button>
        {filtersExpanded ? (
          <>
            {advancedFilters.map((key) => (
              <FilterControl key={key} label={filterLabel(key)} value={filters[key] ?? dictionary.library.filterOptions.any} options={filterOptions(key)} onChange={(next) => updateFilter(key, next)} />
            ))}
            <label className="filter-search">
              <Search size={17} />
              <input placeholder={dictionary.app.shell.globalSearchPlaceholder} onChange={(event) => setNotice(`Search scoped to "${event.target.value}"`)} />
              <kbd>{dictionary.common.searchShortcut}</kbd>
            </label>
            <button className="secondary-button filter-action" type="button" onClick={clearFilters}>{dictionary.actions.clearAll}</button>
          </>
        ) : null}
      </div>

      <div className="table-toolbar">
        <div>
          <h2>{dictionary.library.allMemories}</h2>
          <span>{dictionary.library.results}</span>
        </div>
        <div className="toolbar-actions">
          <SelectMenu
            className="toolbar-select"
            label={dictionary.library.filterLabels.sort}
            value={`Last Seen (${sortDescending ? "desc" : "asc"})`}
            options={["Last Seen (desc)", "Last Seen (asc)"]}
            onChange={(next) => {
              setSortDescending(next.includes("desc"));
              setNotice(`Sorted by ${next}`);
            }}
          />
          <SelectMenu
            className="toolbar-select"
            label={dictionary.library.filterLabels.density}
            value={density}
            options={["Comfortable", "Compact"]}
            onChange={(next) => {
              setDensity(next as Density);
              setNotice(`Density set to ${next}`);
            }}
          />
          <button type="button" onClick={() => setNotice("Export queued as CSV")}>
            <ExternalLink size={16} />
            {dictionary.actions.export}
          </button>
          <SelectMenu
            className="toolbar-select"
            label={dictionary.library.filterLabels.savedViews}
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

function FilterControl({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="filter-control">
      <span>{label}</span>
      <SelectMenu className="filter-select" value={value} options={options} onChange={onChange} />
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

function MemoryTimelineView({
  memories,
  selected,
  onSelect,
}: {
  memories: MemoryItem[];
  selected: MemoryItem;
  onSelect: (memory: MemoryItem) => void;
}) {
  const { dictionary } = useI18n();
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
