import { useRef, type PointerEvent, type ReactNode } from "react";
import { ExternalLink, Pin, X, type LucideIcon } from "lucide-react";
import { lifecycleTone, type StatusTone } from "../design-system/status";
import { lifecycleDescription, lifecycleLabel } from "../i18n/formatters";
import { useI18n } from "../i18n";
import type { LifecycleStatus } from "../types/lifecycle";
import { IconButton } from "./buttons";

export function StatusBadge({ status }: { status: LifecycleStatus }) {
  const { dictionary } = useI18n();
  const tone = lifecycleTone[status];
  return (
    <span className={`status-badge status-badge--${tone}`} title={lifecycleDescription(dictionary, status)}>
      <span className={`status-dot status-dot--${tone}`} aria-hidden="true" />
      {lifecycleLabel(dictionary, status)}
    </span>
  );
}

export function StatusPill({ label, tone }: { label: string; tone: StatusTone }) {
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
  onPin,
  pinned,
}: {
  title: string;
  onOpen: () => void;
  onClose?: () => void;
  onPin?: () => void;
  pinned?: boolean;
}) {
  const { dictionary } = useI18n();
  return (
    <div className="inspector-header">
      <h1>{title}</h1>
      <div>
        <IconButton label={dictionary.common.openFullDetail} icon={ExternalLink} onClick={onOpen} />
        <IconButton label={pinned ? dictionary.common.unpinInspector : dictionary.common.pinInspector} icon={Pin} onClick={onPin} />
        <IconButton label={dictionary.common.closeInspector} icon={X} onClick={onClose} />
      </div>
    </div>
  );
}

export function InspectorSection({
  title,
  action,
  onAction,
  children,
}: {
  title: string;
  action?: string;
  onAction?: () => void;
  children: ReactNode;
}) {
  return (
    <section className="inspector-section">
      <div className="section-title-row">
        <h3>{title}</h3>
        {action ? <button type="button" onClick={onAction}>{action}</button> : null}
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

export function DetailTabs({
  tabs,
  activeTab,
  onSelect,
}: {
  tabs: string[];
  activeTab: string;
  onSelect: (tab: string) => void;
}) {
  return <ScrollableTabs tabs={tabs} activeTab={activeTab} onSelect={onSelect} />;
}

export function ScrollableTabs({
  tabs,
  activeTab,
  label,
  onSelect,
}: {
  tabs: string[];
  activeTab: string;
  label?: string;
  onSelect?: (tab: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef({ isDragging: false, startX: 0, scrollLeft: 0 });

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) {
      return;
    }

    if (event.target instanceof Element && event.target.closest("button")) {
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
    event.preventDefault();
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const container = containerRef.current;
    if (!container || !dragRef.current.isDragging) {
      return;
    }

    container.scrollLeft = dragRef.current.scrollLeft - (event.clientX - dragRef.current.startX);
    event.preventDefault();
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
        <button
          key={tab}
          className={tab === activeTab || (!activeTab && index === 0) ? "is-active" : ""}
          role="tab"
          aria-selected={tab === activeTab || (!activeTab && index === 0)}
          type="button"
          onClick={() => onSelect?.(tab)}
        >
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
