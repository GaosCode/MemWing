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
import { BrandMark } from "../shared/components/BrandMark";
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
  return (
    <div className={`app-shell app-shell--${shellMode}`}>
      <Sidebar active={activeNav} onSelect={onSelectNav} />
      <Topbar />
      <main className="workspace" aria-label="MemWing workspace">
        {children}
      </main>
      <Statusbar />
    </div>
  );
}

function Sidebar({ active, onSelect }: { active: NavKey; onSelect: (key: NavKey) => void }) {
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

      <button className="collapse-button" type="button">
        <ArrowLeft size={18} />
        <span>Collapse</span>
      </button>
    </nav>
  );
}

function Topbar() {
  return (
    <header className="topbar">
      <div className="scope-group" aria-label="Scope selectors">
        <ScopeButton label="工作区" value="产品记忆治理" />
        <ScopeButton label="分组" value="产品线" />
        <ScopeButton label="线程" value="自动化维护" />
      </div>

      <label className="global-search">
        <Search size={18} />
        <span className="sr-only">Search</span>
        <input placeholder="搜索记忆、来源、标签、ID..." />
        <kbd>⌘ K</kbd>
      </label>

      <div className="sync-user">
        <RefreshCcw size={20} />
        <span className="status-dot status-dot--green" aria-hidden="true" />
        <span className="sync-text">已同步 2 分钟前</span>
        <span className="avatar" aria-hidden="true">
          <User size={16} />
        </span>
        <span className="user-name">swift.gao</span>
        <ChevronDown size={16} />
      </div>
    </header>
  );
}

function ScopeButton({ label, value }: { label: string; value: string }) {
  return (
    <button className="scope-button" type="button">
      <span>
        <span className="scope-kicker">{label}</span>
        <span className="scope-value">{value}</span>
      </span>
      <ChevronDown size={16} />
    </button>
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
