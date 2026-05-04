import { useMemo, useState } from "react";
import { RefreshCcw } from "lucide-react";
import "./controlPlaneState.css";
import { AppShell } from "./AppShell";
import { maintenanceKey, useControlPlaneData } from "./useControlPlaneData";
import { Button, SplitSurface } from "../shared/components/ui";
import type { DetailMode, MaintenanceItem, MemoryItem, NavKey } from "../shared/types/entities";
import { InboxPage } from "../features/inbox/InboxPage";
import { LibraryPage } from "../features/library/LibraryPage";
import { MaintenanceDetailPage } from "../features/maintenance/MaintenanceDetailPage";
import { MaintenanceInspector } from "../features/maintenance/MaintenanceInspector";
import { MaintenancePage } from "../features/maintenance/MaintenancePage";
import { MemoryDetailPage } from "../features/memory-detail/MemoryDetailPage";
import { MemoryInspector } from "../features/memory-detail/MemoryInspector";
import { ProjectInspector } from "../features/project/ProjectInspector";
import { ProjectInspectorDetail } from "../features/project/ProjectInspectorDetail";
import { ProjectPage } from "../features/project/ProjectPage";
import { SettingsPage } from "../features/settings/SettingsPage";

export function App() {
  const [activeNav, setActiveNav] = useState<NavKey>("inbox");
  const [detailMode, setDetailMode] = useState<DetailMode>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(400);
  const control = useControlPlaneData();

  function openNav(next: NavKey) {
    setActiveNav(next);
    setDetailMode(null);
    setInspectorOpen(false);
  }

  function selectMemory(memory: MemoryItem) {
    if (inspectorOpen && control.selectedMemory?.id === memory.id) {
      setInspectorOpen(false);
      return;
    }
    control.setSelectedMemoryId(memory.id);
    setInspectorOpen(true);
  }

  function selectMaintenance(item: MaintenanceItem) {
    if (
      inspectorOpen
      && control.selectedMaintenance !== null
      && maintenanceKey(control.selectedMaintenance) === maintenanceKey(item)
    ) {
      setInspectorOpen(false);
      return;
    }
    control.setSelectedMaintenance(item);
    setInspectorOpen(true);
  }

  const inspectorControls = {
    onClose: () => setInspectorOpen(false),
  };

  const splitProps = {
    inspectorOpen,
    inspectorWidth,
    onInspectorWidthChange: setInspectorWidth,
    onReopenInspector: () => setInspectorOpen(true),
  };

  const content = useMemo(() => {
    if (control.loading || control.loadError !== null) {
      return (
        <ControlPlaneState
          loading={control.loading}
          error={control.loadError}
          empty={!control.loading && control.loadError === null}
          onRetry={() => {
            void control.refreshControlPlane();
          }}
        />
      );
    }

    if ((activeNav === "inbox" || activeNav === "library" || detailMode === "memory") && control.selectedMemory === null) {
      return <ControlPlaneState loading={false} error={null} empty onRetry={() => void control.refreshControlPlane()} />;
    }

    if (detailMode === "memory") {
      if (control.selectedMemory === null) {
        return null;
      }
      return (
        <MemoryDetailPage
          memory={control.selectedMemory}
          detail={control.memoryDetails[control.selectedMemory.id] ?? null}
          onBack={() => setDetailMode(null)}
          onLifecycleAction={control.runMemoryLifecycleAction}
          onEditMemory={control.runMemoryEdit}
        />
      );
    }

    if (detailMode === "project") {
      if (control.selectedPage === null) {
        return <ControlPlaneState loading={false} error={null} empty onRetry={() => void control.refreshControlPlane()} />;
      }
      return (
        <ProjectInspectorDetail
          page={control.selectedPage}
          detail={control.selectedPageDetail}
          memories={control.memories}
          onSelectMemory={selectMemory}
          onRebuildPage={control.runPageRebuild}
          onEditPage={control.runPageEdit}
          onRestorePageVersion={control.runPageRestore}
          onBack={() => setDetailMode(null)}
        />
      );
    }

    if (detailMode === "maintenance") {
      return control.selectedMaintenance === null ? null : (
        <MaintenanceDetailPage
          item={control.selectedMaintenance}
          memories={control.memories}
          onAction={control.runMaintenanceAction}
          onBack={() => setDetailMode(null)}
        />
      );
    }

    if (activeNav === "inbox") {
      return (
        <SplitSurface
          {...splitProps}
          main={<InboxPage memories={control.memories} selected={control.selectedMemory} onSelect={selectMemory} />}
          inspector={<MemoryInspector memory={control.selectedMemory} onOpenDetail={() => setDetailMode("memory")} onLifecycleAction={control.runMemoryLifecycleAction} {...inspectorControls} />}
        />
      );
    }

    if (activeNav === "library") {
      return (
        <SplitSurface
          {...splitProps}
          main={<LibraryPage memories={control.memories} selected={control.selectedMemory} onSelect={selectMemory} />}
          inspector={<MemoryInspector memory={control.selectedMemory} onOpenDetail={() => setDetailMode("memory")} onLifecycleAction={control.runMemoryLifecycleAction} libraryMode {...inspectorControls} />}
        />
      );
    }

    if (activeNav === "project") {
      if (control.selectedPage === null) {
        return <ControlPlaneState loading={false} error={null} empty onRetry={() => void control.refreshControlPlane()} />;
      }
      return (
        <SplitSurface
          {...splitProps}
          main={
            <ProjectPage
              page={control.selectedPage}
              detail={control.selectedPageDetail}
              memories={control.memories}
              onSelectMemory={selectMemory}
              onRebuildPage={control.runPageRebuild}
              onEditPage={control.runPageEdit}
              onRestorePageVersion={control.runPageRestore}
            />
          }
          inspector={<ProjectInspector page={control.selectedPage} detail={control.selectedPageDetail} onOpenDetail={() => setDetailMode("project")} {...inspectorControls} />}
        />
      );
    }

    if (activeNav === "maintenance") {
      if (control.selectedMaintenance === null) {
        return <ControlPlaneState loading={false} error={null} empty onRetry={() => void control.refreshControlPlane()} />;
      }
      return (
        <SplitSurface
          {...splitProps}
          main={
            <MaintenancePage
              items={control.maintenanceItems}
              memories={control.memories}
              selected={control.selectedMaintenance}
              onSelect={selectMaintenance}
              onAction={control.runMaintenanceAction}
              onMemoryLifecycleAction={control.runMemoryLifecycleAction}
            />
          }
          inspector={<MaintenanceInspector item={control.selectedMaintenance} onOpenDetail={() => setDetailMode("maintenance")} onAction={control.runMaintenanceAction} {...inspectorControls} />}
        />
      );
    }

    return <SettingsPage settings={control.settings} integrations={control.integrations} onRefresh={() => void control.refreshSettings()} />;
  }, [activeNav, control, detailMode, inspectorOpen, inspectorWidth]);

  return (
    <AppShell activeNav={activeNav} shellMode={detailMode ? "detail" : "split"} onSelectNav={openNav}>
      {content}
    </AppShell>
  );
}

function ControlPlaneState({
  loading,
  error,
  empty,
  onRetry,
}: {
  loading: boolean;
  error: string | null;
  empty?: boolean;
  onRetry: () => void;
}) {
  return (
    <section className="control-plane-state">
      <h1>{loading ? "Loading MemWing" : empty ? "No MemWing records" : "MemWing API unavailable"}</h1>
      <p>{loading ? "Fetching current memory state from the backend." : empty ? "The backend returned an empty control plane result for the current scope." : error}</p>
      {!loading ? <Button icon={RefreshCcw} label="Retry" onClick={onRetry} /> : null}
    </section>
  );
}
