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
import type { NavKey } from "../shared/types/entities";

const navItems: Array<{ key: NavKey; icon: LucideIcon }> = [
  { key: "inbox", icon: Inbox },
  { key: "library", icon: BookOpen },
  { key: "project", icon: Folder },
  { key: "maintenance", icon: Wrench },
  { key: "settings", icon: Settings },
];

export function AppShell({
  activeNav,
  shellMode,
  children,
  onSelectNav,
}: {
  activeNav: NavKey;
  shellMode: "split" | "detail";
  children: React.ReactNode;
  onSelectNav: (key: NavKey) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const { dictionary } = useI18n();
  return (
    <div className={`app-shell app-shell--${shellMode} ${collapsed ? "app-shell--nav-collapsed" : ""}`}>
      <Sidebar active={activeNav} collapsed={collapsed} onToggleCollapse={() => setCollapsed((value) => !value)} onSelect={onSelectNav} />
      <Topbar />
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

function Topbar() {
  const { locale, dictionary, setLocale } = useI18n();
  const [workspaceIndex, setWorkspaceIndex] = useState(0);
  const [groupIndex, setGroupIndex] = useState(0);
  const [threadIndex, setThreadIndex] = useState(0);
  const [search, setSearch] = useState("");
  const [syncedNow, setSyncedNow] = useState(false);
  const languageValue = locale === "zh-CN" ? dictionary.app.shell.languageChinese : dictionary.app.shell.languageEnglish;

  function changeLocale(nextLabel: string) {
    setLocale(nextLabel === dictionary.app.shell.languageEnglish ? "en" : "zh-CN");
  }

  return (
    <header className="topbar">
      <div className="scope-group" aria-label={dictionary.app.shell.scopeAria}>
        <SelectMenu
          className="scope-select"
          label={dictionary.app.shell.workspaceLabel}
          value={dictionary.app.shell.workspaceOptions[workspaceIndex]}
          options={[...dictionary.app.shell.workspaceOptions]}
          onChange={(next) => setWorkspaceIndex(dictionary.app.shell.workspaceOptions.indexOf(next))}
        />
        <SelectMenu
          className="scope-select"
          label={dictionary.app.shell.groupLabel}
          value={dictionary.app.shell.groupOptions[groupIndex]}
          options={[...dictionary.app.shell.groupOptions]}
          onChange={(next) => setGroupIndex(dictionary.app.shell.groupOptions.indexOf(next))}
        />
        <SelectMenu
          className="scope-select"
          label={dictionary.app.shell.threadLabel}
          value={dictionary.app.shell.threadOptions[threadIndex]}
          options={[...dictionary.app.shell.threadOptions]}
          onChange={(next) => setThreadIndex(dictionary.app.shell.threadOptions.indexOf(next))}
        />
      </div>

      <label className="global-search">
        <Search size={18} />
        <span className="sr-only">{dictionary.app.shell.globalSearchLabel}</span>
        <input value={search} placeholder={dictionary.app.shell.globalSearchPlaceholder} onChange={(event) => setSearch(event.target.value)} />
        <kbd>{dictionary.common.searchShortcut}</kbd>
        {search ? <span className="search-result-hint">{dictionary.app.shell.localFilterPrefix}{search}</span> : null}
      </label>

      <button className="sync-user" type="button" onClick={() => setSyncedNow(true)}>
        <RefreshCcw size={20} />
        <span className="status-dot status-dot--green" aria-hidden="true" />
        <span className="sync-text">{syncedNow ? dictionary.app.shell.syncedNow : dictionary.app.shell.syncedRecently}</span>
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
