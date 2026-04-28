import { useRef, type PointerEvent, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, ExternalLink, Pin, X, type LucideIcon } from "lucide-react";
import { lifecycleStatus } from "../design-system/status";
import type { LifecycleStatus } from "../types/lifecycle";

export type InspectorSize = "compact" | "regular" | "wide";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {actions ? <div className="header-actions">{actions}</div> : null}
    </div>
  );
}

export function SplitSurface({
  main,
  inspector,
  inspectorOpen = true,
  inspectorSize = "regular",
  onReopenInspector,
}: {
  main: ReactNode;
  inspector: ReactNode;
  inspectorOpen?: boolean;
  inspectorSize?: InspectorSize;
  onReopenInspector?: () => void;
}) {
  return (
    <div className={`split-surface split-surface--${inspectorOpen ? inspectorSize : "closed"}`}>
      <section className="work-area">{main}</section>
      {inspectorOpen ? (
        <aside className="inspector-rail" aria-label="Inspector">
          {inspector}
        </aside>
      ) : (
        <button
          className="inspector-edge-hotspot"
          type="button"
          aria-label="Open inspector"
          title="Open inspector"
          onClick={onReopenInspector}
          onFocus={onReopenInspector}
          onMouseEnter={onReopenInspector}
          onPointerEnter={onReopenInspector}
        />
      )}
    </div>
  );
}

export function Button({
  icon: Icon,
  label,
  primary,
  danger,
}: {
  icon: LucideIcon;
  label: string;
  primary?: boolean;
  danger?: boolean;
}) {
  return (
    <button className={`button ${primary ? "button--primary" : ""} ${danger ? "button--danger" : ""}`} type="button">
      <Icon size={17} />
      {label}
    </button>
  );
}

export function IconButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
}) {
  return (
    <button className="icon-button" type="button" aria-label={label} title={label} onClick={onClick}>
      <Icon size={18} />
    </button>
  );
}

export function StatusBadge({ status }: { status: LifecycleStatus }) {
  const meta = lifecycleStatus[status];
  return (
    <span className={`status-badge status-badge--${meta.tone}`} title={meta.description}>
      <span className={`status-dot status-dot--${meta.tone}`} aria-hidden="true" />
      {meta.label}
    </span>
  );
}

export function StatusPill({ label, tone }: { label: string; tone: "green" | "orange" | "red" | "gray" }) {
  return (
    <span className={`status-pill status-pill--${tone}`}>
      <span className={`status-dot status-dot--${tone}`} />
      {label}
    </span>
  );
}

export function StrengthMeter({ value, compact }: { value: number; compact?: boolean }) {
  return (
    <span className={`strength-meter ${compact ? "strength-meter--compact" : ""}`}>
      <span>{value.toFixed(2)}</span>
      <span className="meter-track" aria-hidden="true">
        <span style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
    </span>
  );
}

export function Definition({ label, children }: { label: string; children: ReactNode }) {
  return (
    <dl className="definition">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </dl>
  );
}

export function Metric({
  label,
  value,
  tone,
  meter,
}: {
  label: string;
  value: string;
  tone?: "green" | "orange" | "red";
  meter?: boolean;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone ? `text-${tone}` : ""}>{value}</strong>
      {meter ? <StrengthMeter value={0.84} compact /> : null}
    </div>
  );
}

export function InspectorHeader({
  title,
  onOpen,
  onClose,
  onNarrow,
  onWiden,
}: {
  title: string;
  onOpen: () => void;
  onClose?: () => void;
  onNarrow?: () => void;
  onWiden?: () => void;
}) {
  return (
    <div className="inspector-header">
      <h1>{title}</h1>
      <div>
        <IconButton label="Narrow inspector" icon={ChevronRight} onClick={onNarrow} />
        <IconButton label="Widen inspector" icon={ChevronLeft} onClick={onWiden} />
        <IconButton label="Open full detail" icon={ExternalLink} onClick={onOpen} />
        <IconButton label="Pin inspector" icon={Pin} />
        <IconButton label="Close inspector" icon={X} onClick={onClose} />
      </div>
    </div>
  );
}

export function InspectorSection({ title, action, children }: { title: string; action?: string; children: ReactNode }) {
  return (
    <section className="inspector-section">
      <div className="section-title-row">
        <h3>{title}</h3>
        {action ? <button>{action}</button> : null}
      </div>
      {children}
    </section>
  );
}

export function DocSection({
  icon: Icon,
  index,
  title,
  tag,
  children,
}: {
  icon: LucideIcon;
  index?: string;
  title: string;
  tag?: string;
  children: ReactNode;
}) {
  return (
    <section className="doc-section">
      <div className="doc-section-title">
        <Icon size={20} />
        <h2>{index ? `${index}. ${title}` : title}</h2>
        {tag ? <span className="soft-tag">{tag}</span> : null}
      </div>
      <div className="doc-section-body">{children}</div>
    </section>
  );
}

export function DetailTabs({ tabs }: { tabs: string[] }) {
  return <ScrollableTabs tabs={tabs} activeTab={tabs[0]} />;
}

export function ScrollableTabs({
  tabs,
  activeTab,
  label,
}: {
  tabs: string[];
  activeTab: string;
  label?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef({ isDragging: false, startX: 0, scrollLeft: 0 });

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) {
      return;
    }

    const container = containerRef.current;
    if (!container) {
      return;
    }

    dragRef.current = {
      isDragging: true,
      startX: event.clientX,
      scrollLeft: container.scrollLeft,
    };
    container.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const container = containerRef.current;
    if (!container || !dragRef.current.isDragging) {
      return;
    }

    container.scrollLeft = dragRef.current.scrollLeft - (event.clientX - dragRef.current.startX);
  }

  function endDrag(event: PointerEvent<HTMLDivElement>) {
    const container = containerRef.current;
    dragRef.current.isDragging = false;
    if (container?.hasPointerCapture(event.pointerId)) {
      container.releasePointerCapture(event.pointerId);
    }
  }

  return (
    <div
      ref={containerRef}
      className="tabs"
      role="tablist"
      aria-label={label}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerCancel={endDrag}
      onPointerUp={endDrag}
    >
      {tabs.map((tab, index) => (
        <button key={tab} className={tab === activeTab || (!activeTab && index === 0) ? "is-active" : ""} role="tab" type="button">
          {tab}
        </button>
      ))}
    </div>
  );
}

export function Timeline({ rows, compact }: { rows: string[]; compact?: boolean }) {
  return (
    <ol className={`timeline ${compact ? "timeline--compact" : ""}`}>
      {rows.map((row) => (
        <li key={row}>
          <span className="status-dot status-dot--green" aria-hidden="true" />
          <span>{row}</span>
        </li>
      ))}
    </ol>
  );
}

export function SimpleTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <div className="simple-table">
      <div className="simple-table-row simple-table-row--head">
        {columns.map((column) => <span key={column}>{column}</span>)}
      </div>
      {rows.map((row, rowIndex) => (
        <div className="simple-table-row" key={`${rowIndex}-${row.join("-")}`}>
          {row.map((cell, cellIndex) => <span key={`${cellIndex}-${cell}`}>{cell}</span>)}
        </div>
      ))}
    </div>
  );
}
