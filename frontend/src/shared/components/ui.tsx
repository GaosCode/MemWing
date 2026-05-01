import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { ChevronDown, ExternalLink, Pin, X, type LucideIcon } from "lucide-react";
import { lifecycleTone, type StatusTone } from "../design-system/status";
import { lifecycleDescription, lifecycleLabel } from "../i18n/formatters";
import { useI18n } from "../i18n";
import type { LifecycleStatus } from "../types/lifecycle";

const MIN_INSPECTOR_WIDTH = 320;
const MAX_INSPECTOR_WIDTH = 560;
const SELECT_MENU_OPEN_EVENT = "memwing-select-menu-open";

function clampInspectorWidth(width: number) {
  return Math.min(MAX_INSPECTOR_WIDTH, Math.max(MIN_INSPECTOR_WIDTH, width));
}

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
  inspectorWidth = 400,
  onInspectorWidthChange,
  onReopenInspector,
}: {
  main: ReactNode;
  inspector: ReactNode;
  inspectorOpen?: boolean;
  inspectorWidth?: number;
  onInspectorWidthChange?: (width: number) => void;
  onReopenInspector?: () => void;
}) {
  const { dictionary } = useI18n();
  const surfaceRef = useRef<HTMLDivElement>(null);
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null);
  const handleDragState = useRef<{ startX: number; startY: number; startTop: number; moved: boolean } | null>(null);
  const [handleTop, setHandleTop] = useState(58);
  const clampedWidth = clampInspectorWidth(inspectorWidth);
  const surfaceStyle = {
    "--inspector-panel-width": `${clampedWidth}px`,
  } as CSSProperties;
  const handleStyle = {
    "--inspector-handle-top": `${handleTop}%`,
  } as CSSProperties;

  function changeWidth(nextWidth: number) {
    onInspectorWidthChange?.(clampInspectorWidth(nextWidth));
  }

  function handleResizePointerDown(event: PointerEvent<HTMLDivElement>) {
    dragState.current = { startX: event.clientX, startWidth: clampedWidth };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function handleResizePointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!dragState.current) {
      return;
    }

    changeWidth(dragState.current.startWidth + dragState.current.startX - event.clientX);
  }

  function clearResizeDrag(event: PointerEvent<HTMLDivElement>) {
    dragState.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleResizeKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") {
      changeWidth(clampedWidth + 24);
      event.preventDefault();
    }
    if (event.key === "ArrowRight") {
      changeWidth(clampedWidth - 24);
      event.preventDefault();
    }
  }

  function changeHandleTop(nextTop: number) {
    setHandleTop(Math.min(84, Math.max(18, nextTop)));
  }

  function handleHandlePointerDown(event: PointerEvent<HTMLDivElement>) {
    handleDragState.current = { startX: event.clientX, startY: event.clientY, startTop: handleTop, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function handleHandlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const currentDrag = handleDragState.current;
    const surface = surfaceRef.current;
    if (!currentDrag || !surface) {
      return;
    }

    const surfaceHeight = surface.getBoundingClientRect().height || 1;
    const delta = ((event.clientY - currentDrag.startY) / surfaceHeight) * 100;
    const movedDistance = Math.hypot(event.clientX - currentDrag.startX, event.clientY - currentDrag.startY);
    if (movedDistance > 4) {
      currentDrag.moved = true;
    }
    changeHandleTop(currentDrag.startTop + delta);
  }

  function clearHandleDrag(event: PointerEvent<HTMLDivElement>) {
    const currentDrag = handleDragState.current;
    handleDragState.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (!currentDrag?.moved) {
      onReopenInspector?.();
    }
  }

  function handleHandleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      onReopenInspector?.();
      event.preventDefault();
    }
    if (event.key === "ArrowUp") {
      changeHandleTop(handleTop - 5);
      event.preventDefault();
    }
    if (event.key === "ArrowDown") {
      changeHandleTop(handleTop + 5);
      event.preventDefault();
    }
  }

  return (
    <div ref={surfaceRef} className={`split-surface split-surface--${inspectorOpen ? "open" : "closed"}`} style={surfaceStyle}>
      <section className="work-area">{main}</section>
      {inspectorOpen ? (
        <>
          <div
            className="inspector-resizer"
            role="separator"
            aria-label={dictionary.common.resizeInspector}
            aria-orientation="vertical"
            aria-valuemin={MIN_INSPECTOR_WIDTH}
            aria-valuemax={MAX_INSPECTOR_WIDTH}
            aria-valuenow={clampedWidth}
            tabIndex={0}
            onKeyDown={handleResizeKeyDown}
            onPointerDown={handleResizePointerDown}
            onPointerMove={handleResizePointerMove}
            onPointerUp={clearResizeDrag}
            onPointerCancel={clearResizeDrag}
          />
          <aside className="inspector-rail" aria-label="Inspector">
            {inspector}
          </aside>
        </>
      ) : (
        <div
          className="inspector-floating-handle"
          role="button"
          aria-label={dictionary.common.openInspector}
          title={dictionary.common.openInspector}
          tabIndex={0}
          style={handleStyle}
          onKeyDown={handleHandleKeyDown}
          onPointerDown={handleHandlePointerDown}
          onPointerMove={handleHandlePointerMove}
          onPointerUp={clearHandleDrag}
          onPointerCancel={clearHandleDrag}
        >
          <span>{dictionary.common.inspector}</span>
        </div>
      )}
    </div>
  );
}

export function Button({
  icon: Icon,
  label,
  primary,
  danger,
  onClick,
  disabled,
}: {
  icon: LucideIcon;
  label: string;
  primary?: boolean;
  danger?: boolean;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      className={`button ${primary ? "button--primary" : ""} ${danger ? "button--danger" : ""}`}
      type="button"
      onClick={onClick}
      disabled={disabled}
    >
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

export function SelectMenu({
  label,
  value,
  options,
  className,
  onChange,
}: {
  label?: string;
  value: string;
  options: string[];
  className: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    function closeForExternalOpen(event: Event) {
      if ((event as CustomEvent<string>).detail !== menuId) {
        setOpen(false);
      }
    }

    function closeForOutsidePointer(event: Event) {
      const target = event.target;
      if (target instanceof Node && rootRef.current?.contains(target)) {
        return;
      }
      setOpen(false);
    }

    window.addEventListener(SELECT_MENU_OPEN_EVENT, closeForExternalOpen as EventListener);
    window.addEventListener("pointerdown", closeForOutsidePointer, true);
    return () => {
      window.removeEventListener(SELECT_MENU_OPEN_EVENT, closeForExternalOpen as EventListener);
      window.removeEventListener("pointerdown", closeForOutsidePointer, true);
    };
  }, [menuId, open]);

  return (
    <div
      ref={rootRef}
      className={`${className} ${open ? "is-open" : ""}`}
      onBlur={(event) => {
        const nextTarget = event.relatedTarget;
        if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
          return;
        }
        setOpen(false);
      }}
    >
      <button
        className={`${className}__button`}
        type="button"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => {
          setOpen((current) => {
            const nextOpen = !current;
            if (nextOpen) {
              window.dispatchEvent(new CustomEvent<string>(SELECT_MENU_OPEN_EVENT, { detail: menuId }));
            }
            return nextOpen;
          });
        }}
      >
        <span className={`${className}__content`}>
          {label ? <span className={`${className}__label`}>{label}</span> : null}
          <span className={`${className}__value`}>{value}</span>
        </span>
        <ChevronDown size={16} />
      </button>
      {open ? (
        <div className={`${className}__menu`} id={menuId} role="listbox">
          {options.map((option) => (
            <button
              key={option}
              className={option === value ? "is-active" : ""}
              type="button"
              role="option"
              aria-selected={option === value}
              onClick={() => {
                onChange(option);
                setOpen(false);
              }}
            >
              {option}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

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
