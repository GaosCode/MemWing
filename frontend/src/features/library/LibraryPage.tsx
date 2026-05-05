import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Check, Clock3, Columns3, ExternalLink, List, ListFilter, Plus, Search } from "lucide-react";
import { PageHeader, SelectMenu } from "../../shared/components/ui";
import type { ManualMemoryCreateResult, ManualMemoryInput } from "../../shared/api/controlPlaneClient";
import { useI18n } from "../../shared/i18n";
import type { MemoryItem } from "../../shared/types/entities";
import { exportLibraryMemoriesCsv, filterLibraryMemories } from "./libraryControls";
import { MemoryBoardView, MemoryListView, MemoryTimelineView, type Density, type LibraryView } from "./LibraryViews";

const primaryFilters = ["project", "group", "thread", "type", "lifecycle"] as const;
const advancedFilters = ["strength", "pinned", "archived", "hidden", "needsReview", "sourcePlatform", "time"] as const;
type FilterKey = (typeof primaryFilters)[number] | (typeof advancedFilters)[number];

export function LibraryPage({
  memories,
  selected,
  onSelect,
  onCreateMemory,
}: {
  memories: MemoryItem[];
  selected: MemoryItem;
  onSelect: (memory: MemoryItem) => void;
  onCreateMemory: (input: ManualMemoryInput) => Promise<ManualMemoryCreateResult>;
}) {
  const { dictionary } = useI18n();
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [view, setView] = useState<LibraryView>("List");
  const [density, setDensity] = useState<Density>("Comfortable");
  const [sortDescending, setSortDescending] = useState(true);
  const [savedView, setSavedView] = useState("Default");
  const [notice, setNotice] = useState(dictionary.library.ready);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [memoryComposerOpen, setMemoryComposerOpen] = useState(false);

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
    setSearchQuery("");
    setNotice("Filters cleared");
  }

  const visibleMemories = useMemo(
    () => filterLibraryMemories({
      memories,
      filters,
      savedView,
      searchQuery,
      sortDescending,
      dictionary,
    }),
    [dictionary, filters, memories, savedView, searchQuery, sortDescending],
  );

  return (
    <>
      <PageHeader
        title={dictionary.library.title}
        subtitle={dictionary.library.subtitle}
        actions={
          <>
            <button
              className="button button--primary"
              type="button"
              onMouseDown={() => setMemoryComposerOpen(true)}
              onClick={() => setMemoryComposerOpen(true)}
            >
              <Plus size={17} />
              新增记忆
            </button>
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
          </>
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
              <input
                value={searchQuery}
                placeholder={dictionary.app.shell.globalSearchPlaceholder}
                onChange={(event) => {
                  setSearchQuery(event.target.value);
                  setNotice(`Search scoped to "${event.target.value}"`);
                }}
              />
              <kbd>{dictionary.common.searchShortcut}</kbd>
            </label>
            <button className="secondary-button filter-action" type="button" onClick={clearFilters}>{dictionary.actions.clearAll}</button>
          </>
        ) : null}
      </div>

      <div className="table-toolbar">
        <div>
          <h2>{dictionary.library.allMemories}</h2>
          <span>{visibleMemories.length} / {memories.length} records</span>
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
          <button type="button" onClick={() => exportMemories(visibleMemories)}>
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
              setNotice(`Saved view applied: ${next}`);
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
      <AddMemoryDialog
        open={memoryComposerOpen}
        onClose={() => setMemoryComposerOpen(false)}
        onSubmit={submitMemoryCreate}
      />
    </>
  );

  async function submitMemoryCreate(input: ManualMemoryInput) {
    const result = await onCreateMemory(input);
    if (result.visibleMemoryId !== null) {
      setNotice(`已提交新增记忆，候选项 ${result.visibleMemoryId} 已出现在列表中。`);
      return;
    }
    setNotice(`已提交新增记忆事件 ${result.source_event_id}，后端管线生成候选记忆后会出现在列表中。`);
  }

  function exportMemories(records: MemoryItem[]) {
    exportLibraryMemoriesCsv(records);
    setNotice(`Exported ${records.length} records as CSV`);
  }
}

function FilterControl({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="filter-control">
      <span>{label}</span>
      <SelectMenu className="filter-select" value={value} options={options} onChange={onChange} />
    </label>
  );
}

function AddMemoryDialog({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (input: ManualMemoryInput) => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [reason, setReason] = useState("手动新增记忆");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setTitle("");
    setContent("");
    setSourceUrl("");
    setReason("手动新增记忆");
    setError(null);
    setSubmitting(false);
  }, [open]);

  if (!open) {
    return null;
  }

  const canSubmit = title.trim().length > 0 && content.trim().length > 0 && reason.trim().length > 0;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || submitting) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        title: title.trim(),
        content: content.trim(),
        sourceUrl: sourceUrl.trim().length > 0 ? sourceUrl.trim() : null,
        reason: reason.trim(),
      });
      onClose();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "新增记忆提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) {
        onClose();
      }
    }}>
      <form className="memory-create-dialog" aria-label="新增记忆" onSubmit={submit}>
        <div className="dialog-header">
          <div>
            <h2>新增记忆</h2>
            <p>提交后写入 MemWing 事件管线，由后端生成候选记忆和审计记录。</p>
          </div>
          <button type="button" aria-label="关闭新增记忆" onClick={onClose}>×</button>
        </div>
        <label>
          <span>标题</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：Demo 范围优先飞书文档记忆" />
        </label>
        <label>
          <span>内容</span>
          <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={5} placeholder="写下需要 MemWing 记住的事实、偏好、规则或决策。" />
        </label>
        <label>
          <span>来源链接</span>
          <input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="可选" />
        </label>
        <label>
          <span>原因</span>
          <input value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
        {error ? <p className="dialog-error">{error}</p> : null}
        <div className="dialog-actions">
          <button className="button" type="button" onClick={onClose}>取消</button>
          <button className="button button--primary" type="submit" disabled={!canSubmit || submitting}>
            {submitting ? "提交中" : "提交记忆"}
          </button>
        </div>
      </form>
    </div>
  );
}
