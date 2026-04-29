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
import type { NavKey } from "../shared/types/entities";

const navItems: Array<{ key: NavKey; label: string; icon: LucideIcon }> = [
  { key: "inbox", label: "Inbox", icon: Inbox },
  { key: "library", label: "Library", icon: BookOpen },
  { key: "project", label: "Project", icon: Folder },
  { key: "maintenance", label: "Maintenance", icon: Wrench },
  { key: "settings", label: "Settings", icon: Settings },
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
  return (
    <div className={`app-shell app-shell--${shellMode} ${collapsed ? "app-shell--nav-collapsed" : ""}`}>
      <Sidebar active={activeNav} collapsed={collapsed} onToggleCollapse={() => setCollapsed((value) => !value)} onSelect={onSelectNav} />
      <Topbar />
      <main className="workspace" aria-label="MemWing workspace">
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
  return (
    <nav className="sidebar" aria-label="Primary navigation">
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
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      <button className="collapse-button" type="button" onClick={onToggleCollapse}>
        <ArrowLeft size={18} />
        <span>{collapsed ? "Expand" : "Collapse"}</span>
      </button>
    </nav>
  );
}

function Topbar() {
  const [workspace, setWorkspace] = useState("产品记忆治理");
  const [group, setGroup] = useState("产品线");
  const [thread, setThread] = useState("自动化维护");
  const [search, setSearch] = useState("");
  const [syncedAt, setSyncedAt] = useState("已同步 2 分钟前");

  return (
    <header className="topbar">
      <div className="scope-group" aria-label="Scope selectors">
        <SelectMenu className="scope-select" label="工作区" value={workspace} options={["产品记忆治理", "安全群治理", "A3 Calm Ops"]} onChange={setWorkspace} />
        <SelectMenu className="scope-select" label="分组" value={group} options={["产品线", "安全群", "AI 自动化维护"]} onChange={setGroup} />
        <SelectMenu className="scope-select" label="线程" value={thread} options={["自动化维护", "项目记忆重建", "遗忘曲线复习"]} onChange={setThread} />
      </div>

      <label className="global-search">
        <Search size={18} />
        <span className="sr-only">Search</span>
        <input value={search} placeholder="搜索记忆、来源、标签、ID..." onChange={(event) => setSearch(event.target.value)} />
        <kbd>⌘ K</kbd>
        {search ? <span className="search-result-hint">本地筛选：{search}</span> : null}
      </label>

      <button className="sync-user" type="button" onClick={() => setSyncedAt("刚刚同步")}>
        <RefreshCcw size={20} />
        <span className="status-dot status-dot--green" aria-hidden="true" />
        <span className="sync-text">{syncedAt}</span>
        <span className="avatar" aria-hidden="true">
          <User size={16} />
        </span>
        <span className="user-name">swift.gao</span>
        <ChevronDown size={16} />
      </button>
    </header>
  );
}

function Statusbar() {
  return (
    <footer className="statusbar">
      <span><Activity size={16} /> Jobs: Extraction 2 · Redaction 1 · Conflict Scan running</span>
      <span><span className="status-dot status-dot--green" /> Recent automation: 14 memories refreshed, 2 conflicts detected, 1 source redacted</span>
      <span>Inbox: 13 items</span>
      <span>Uptime: 15d 03h 24m</span>
      <span>11:34 <span className="status-dot status-dot--green" /></span>
    </footer>
  );
}
