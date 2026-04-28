import { useState } from "react";
import { Archive, ChevronDown, Clock3, Columns3, ExternalLink, List, ListFilter, Search } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { IconButton, PageHeader, StatusBadge, StrengthMeter } from "../../shared/components/ui";
import { memoryTypeLabel } from "../../shared/design-system/status";
import type { MemoryItem } from "../../shared/types/entities";

const primaryFilters = ["Project", "Group", "Thread", "Type", "Lifecycle Status"];
const advancedFilters = ["Strength", "Pinned", "Archived", "Hidden", "Needs Review", "Source Platform", "Time"];

export function LibraryPage({ selected, onSelect }: { selected: MemoryItem; onSelect: (memory: MemoryItem) => void }) {
  const [filtersExpanded, setFiltersExpanded] = useState(false);

  return (
    <>
      <PageHeader
        title="Memory Library"
        subtitle="Search, inspect, and manage long-term memory across lifecycle states."
        actions={
          <div className="segmented">
            <button className="is-active"><List size={18} />List</button>
            <button><Clock3 size={18} />Timeline</button>
            <button><Columns3 size={18} />Board</button>
          </div>
        }
      />

      <div className={`filter-grid ${filtersExpanded ? "is-expanded" : ""}`} aria-label="Library filters">
        {primaryFilters.map((label) => (
          <FilterControl key={label} label={label} />
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
              <FilterControl key={label} label={label} />
            ))}
            <label className="filter-search">
              <Search size={17} />
              <input placeholder="搜索记忆、来源、标签、ID..." />
              <kbd>⌘ K</kbd>
            </label>
            <button className="secondary-button filter-action" type="button">Clear All</button>
          </>
        ) : null}
      </div>

      <div className="table-toolbar">
        <div>
          <h2>All Memories</h2>
          <span>248 results</span>
        </div>
        <div className="toolbar-actions">
          <button>Sort: Last Seen (desc) <ChevronDown size={16} /></button>
          <button>Density: Comfortable <ChevronDown size={16} /></button>
          <button><ExternalLink size={16} />Export</button>
          <button><Archive size={16} />Saved Views <ChevronDown size={16} /></button>
        </div>
      </div>

      <div className="memory-table" role="table" aria-label="Memory table">
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
    </>
  );
}

function FilterControl({ label }: { label: string }) {
  return (
    <label className="filter-control">
      <span>{label}</span>
      <button type="button">Any <ChevronDown size={16} /></button>
    </label>
  );
}
