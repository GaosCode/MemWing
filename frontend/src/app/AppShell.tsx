import {
  Activity,
  ArrowLeft,
  BookOpen,
  ChevronDown,
  Folder,
  Inbox,
  RefreshCcw,
  Search,
  Settings,
  User,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { BrandMark } from "../shared/components/BrandMark";
import { SelectMenu } from "../shared/components/ui";
import { useI18n } from "../shared/i18n";
import type { ControlScopeParams } from "../api/generated/controlPlane";
import type { NavKey } from "../shared/types/entities";

const navItems: Array<{ key: NavKey; icon: LucideIcon }> = [
  { key: "inbox", icon: Inbox },
  { key: "library", icon: BookOpen },
  { key: "project", icon: Folder },
  { key: "maintenance", icon: Wrench },
  { key: "settings", icon: Settings },
];

export type TopbarScopeOptions = {
  workspaces: string[];
  groups: string[];
  threads: string[];
};

export function AppShell({
  activeNav,
  shellMode,
  children,
  onSelectNav,
  onRefresh,
  scope,
  scopeOptions,
  onScopeChange,
  searchQuery,
  searchResultCount,
  onSearchQueryChange,
}: {
  activeNav: NavKey;
  shellMode: "split" | "detail";
  children: React.ReactNode;
  onSelectNav: (key: NavKey) => void;
  onRefresh: () => Promise<void>;
  scope: ControlScopeParams;
  scopeOptions: TopbarScopeOptions;
  onScopeChange: (nextScope: ControlScopeParams) => void;
  searchQuery: string;
  searchResultCount: number | null;
  onSearchQueryChange: (query: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const { dictionary } = useI18n();
  return (
    <div className={`app-shell app-shell--${shellMode} ${collapsed ? "app-shell--nav-collapsed" : ""}`}>
      <Sidebar active={activeNav} collapsed={collapsed} onToggleCollapse={() => setCollapsed((value) => !value)} onSelect={onSelectNav} />
      <Topbar
        scope={scope}
        scopeOptions={scopeOptions}
        searchQuery={searchQuery}
        searchResultCount={searchResultCount}
        onRefresh={onRefresh}
        onScopeChange={onScopeChange}
        onSearchQueryChange={onSearchQueryChange}
      />
      <main className="workspace" aria-label={dictionary.app.shell.workspaceAria}>
        {children}
      </main>
      <Statusbar />
    </div>
  );
}

function Sidebar({
  active,
  collapsed,
  onToggleCollapse,
  onSelect,
}: {
  active: NavKey;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelect: (key: NavKey) => void;
}) {
  const { dictionary } = useI18n();
  return (
    <nav className="sidebar" aria-label={dictionary.app.shell.primaryNavAria}>
      <button className="brand" aria-label="MemWing home" onClick={() => onSelect("inbox")}>
        <BrandMark />
        <span>MemWing</span>
      </button>

      <div className="nav-list">
        {navItems.map((item) => (
          <button
            key={item.key}
            className={`nav-item ${active === item.key ? "is-active" : ""}`}
            aria-current={active === item.key ? "page" : undefined}
            onClick={() => onSelect(item.key)}
          >
            <item.icon size={22} strokeWidth={1.8} />
            <span>{dictionary.app.nav[item.key]}</span>
          </button>
        ))}
      </div>

      <button className="collapse-button" type="button" onClick={onToggleCollapse}>
        <ArrowLeft size={18} />
        <span>{collapsed ? dictionary.app.shell.expand : dictionary.app.shell.collapse}</span>
      </button>
    </nav>
  );
}

function Topbar({
  scope,
  scopeOptions,
  searchQuery,
  searchResultCount,
  onRefresh,
  onScopeChange,
  onSearchQueryChange,
}: {
  scope: ControlScopeParams;
  scopeOptions: TopbarScopeOptions;
  searchQuery: string;
  searchResultCount: number | null;
  onRefresh: () => Promise<void>;
  onScopeChange: (nextScope: ControlScopeParams) => void;
  onSearchQueryChange: (query: string) => void;
}) {
  const { locale, dictionary, setLocale } = useI18n();
  const [syncedNow, setSyncedNow] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const languageValue = locale === "zh-CN" ? dictionary.app.shell.languageChinese : dictionary.app.shell.languageEnglish;
  const allGroupsLabel = locale === "zh-CN" ? "全部分组" : "All groups";
  const allThreadsLabel = locale === "zh-CN" ? "全部线程" : "All threads";
  const workspaceOptions = withCurrent(scopeOptions.workspaces, scope.project_memory_space_id);
  const groupOptions = [allGroupsLabel, ...scopeOptions.groups];
  const threadOptions = [allThreadsLabel, ...scopeOptions.threads];
  const groupValue = scope.group_id ?? allGroupsLabel;
  const threadValue = scope.thread_id ?? allThreadsLabel;

  function changeLocale(nextLabel: string) {
    setLocale(nextLabel === dictionary.app.shell.languageEnglish ? "en" : "zh-CN");
  }

  async function refreshFromBackend() {
    setSyncing(true);
    try {
      await onRefresh();
      setSyncedNow(true);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <header className="topbar">
      <div className="scope-group" aria-label={dictionary.app.shell.scopeAria}>
        <SelectMenu
          className="scope-select"
          label={dictionary.app.shell.workspaceLabel}
          value={scope.project_memory_space_id}
          options={workspaceOptions}
          onChange={(next) => onScopeChange({ ...scope, project_memory_space_id: next, group_id: undefined, thread_id: undefined })}
        />
        <SelectMenu
          className="scope-select"
          label={dictionary.app.shell.groupLabel}
          value={groupValue}
          options={groupOptions}
          onChange={(next) => onScopeChange({ ...scope, group_id: next === allGroupsLabel ? undefined : next })}
        />
        <SelectMenu
          className="scope-select"
          label={dictionary.app.shell.threadLabel}
          value={threadValue}
          options={threadOptions}
          onChange={(next) => onScopeChange({ ...scope, thread_id: next === allThreadsLabel ? undefined : next })}
        />
      </div>

      <label className="global-search">
        <Search size={18} />
        <span className="sr-only">{dictionary.app.shell.globalSearchLabel}</span>
        <input value={searchQuery} placeholder={dictionary.app.shell.globalSearchPlaceholder} onChange={(event) => onSearchQueryChange(event.target.value)} />
        <kbd>{dictionary.common.searchShortcut}</kbd>
        {searchQuery ? (
          <span className="search-result-hint">
            {dictionary.app.shell.localFilterPrefix}{searchQuery}
            {searchResultCount !== null ? ` · ${searchResultCount} matches` : ""}
          </span>
        ) : null}
      </label>

      <button className="sync-user" type="button" onClick={() => void refreshFromBackend()} disabled={syncing}>
        <RefreshCcw size={20} />
        <span className="status-dot status-dot--green" aria-hidden="true" />
        <span className="sync-text">{syncing ? "Syncing" : syncedNow ? dictionary.app.shell.syncedNow : dictionary.app.shell.syncedRecently}</span>
        <span className="avatar" aria-hidden="true">
          <User size={16} />
        </span>
        <span className="user-name">swift.gao</span>
        <span className="language-switch" onClick={(event) => event.stopPropagation()}>
          <SelectMenu
            className="language-select"
            label={dictionary.app.shell.languageLabel}
            value={languageValue}
            options={[dictionary.app.shell.languageChinese, dictionary.app.shell.languageEnglish]}
            onChange={(next) => changeLocale(next)}
          />
        </span>
        <ChevronDown size={16} />
      </button>
    </header>
  );
}

function withCurrent(options: string[], current: string) {
  return options.includes(current) ? options : [current, ...options];
}

function Statusbar() {
  const { dictionary } = useI18n();
  return (
    <footer className="statusbar">
      <span><Activity size={16} /> {dictionary.app.shell.statusJobs}</span>
      <span><span className="status-dot status-dot--green" /> {dictionary.app.shell.statusAutomation}</span>
      <span>{dictionary.app.shell.statusInbox}</span>
      <span>{dictionary.app.shell.statusUptime}</span>
      <span>11:34 <span className="status-dot status-dot--green" /></span>
    </footer>
  );
}
