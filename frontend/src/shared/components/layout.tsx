import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { useI18n } from "../i18n";

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
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null);
  const handleDragState = useRef<{ startX: number; startY: number; startTop: number; moved: boolean } | null>(null);
  const handleRef = useRef<HTMLDivElement>(null);
  const [handleTopPx, setHandleTopPx] = useState<number | null>(null);
  const clampedWidth = clampInspectorWidth(inspectorWidth);
  const surfaceStyle = {
    "--inspector-panel-width": `${clampedWidth}px`,
  } as CSSProperties;
  const handleStyle = (handleTopPx === null
    ? { top: "50%" }
    : {
        top: `${handleTopPx}px`,
        "--inspector-handle-transform": "none",
        "--inspector-handle-hover-transform": "translateX(-2px)",
      }) as CSSProperties;

  useEffect(() => {
    if (handleTopPx === null) {
      return undefined;
    }

    function clampHandleToViewport() {
      const handle = handleRef.current;
      if (!handle) {
        return;
      }

      const handleHeight = handle.getBoundingClientRect().height;
      setHandleTopPx((currentTop) => (
        currentTop === null ? currentTop : clampHandleTop(currentTop, handleHeight)
      ));
    }

    clampHandleToViewport();
    window.addEventListener("resize", clampHandleToViewport);
    return () => window.removeEventListener("resize", clampHandleToViewport);
  }, [handleTopPx, inspectorOpen]);

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

  function clampHandleTop(top: number, handleHeight: number) {
    const maxTop = Math.max(0, window.innerHeight - handleHeight);
    return Math.min(maxTop, Math.max(0, top));
  }

  function moveHandleBy(deltaY: number) {
    const handle = handleRef.current;
    if (!handle) {
      return;
    }

    const rect = handle.getBoundingClientRect();
    setHandleTopPx(clampHandleTop(rect.top + deltaY, rect.height));
  }

  function handleHandlePointerDown(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    handleDragState.current = { startX: event.clientX, startY: event.clientY, startTop: rect.top, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function handleHandlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const currentDrag = handleDragState.current;
    if (!currentDrag) {
      return;
    }

    const movedDistance = Math.hypot(event.clientX - currentDrag.startX, event.clientY - currentDrag.startY);
    if (movedDistance <= 4 && !currentDrag.moved) {
      return;
    }

    currentDrag.moved = true;
    const handleHeight = event.currentTarget.getBoundingClientRect().height;
    setHandleTopPx(clampHandleTop(currentDrag.startTop + event.clientY - currentDrag.startY, handleHeight));
  }

  function clearHandleDrag(event: PointerEvent<HTMLDivElement>, shouldOpenOnClick = true) {
    const currentDrag = handleDragState.current;
    handleDragState.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (shouldOpenOnClick && !currentDrag?.moved) {
      onReopenInspector?.();
    }
  }

  function handleHandleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      onReopenInspector?.();
      event.preventDefault();
    }
    if (event.key === "ArrowUp") {
      moveHandleBy(-16);
      event.preventDefault();
    }
    if (event.key === "ArrowDown") {
      moveHandleBy(16);
      event.preventDefault();
    }
  }

  return (
    <div className={`split-surface split-surface--${inspectorOpen ? "open" : "closed"}`} style={surfaceStyle}>
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
          ref={handleRef}
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
          onPointerCancel={(event) => clearHandleDrag(event, false)}
        >
          <span>{dictionary.common.inspector}</span>
        </div>
      )}
    </div>
  );
}
