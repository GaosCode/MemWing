import { useMemo, useState } from "react";
import { AppShell } from "./AppShell";
import { maintenanceItems, memories } from "../shared/api/mockData";
import { SplitSurface } from "../shared/components/ui";
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

function maintenanceKey(item: MaintenanceItem) {
  return `${item.type}:${item.title}:${item.updated}`;
}

export function App() {
  const [activeNav, setActiveNav] = useState<NavKey>("inbox");
  const [detailMode, setDetailMode] = useState<DetailMode>(null);
  const [selectedMemory, setSelectedMemory] = useState<MemoryItem>(memories[0]);
  const [selectedMaintenance, setSelectedMaintenance] = useState<MaintenanceItem>(maintenanceItems[0]);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(400);

  function openNav(next: NavKey) {
    setActiveNav(next);
    setDetailMode(null);
    setInspectorOpen(false);
  }

  function selectMemory(memory: MemoryItem) {
    if (inspectorOpen && selectedMemory.id === memory.id) {
      setInspectorOpen(false);
      return;
    }

    setSelectedMemory(memory);
    setInspectorOpen(true);
  }

  function selectMaintenance(item: MaintenanceItem) {
    if (inspectorOpen && maintenanceKey(selectedMaintenance) === maintenanceKey(item)) {
      setInspectorOpen(false);
      return;
    }

    setSelectedMaintenance(item);
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
    if (detailMode === "memory") {
      return <MemoryDetailPage memory={selectedMemory} onBack={() => setDetailMode(null)} />;
    }

    if (detailMode === "project") {
      return <ProjectInspectorDetail onBack={() => setDetailMode(null)} />;
    }

    if (detailMode === "maintenance") {
      return <MaintenanceDetailPage item={selectedMaintenance} onBack={() => setDetailMode(null)} />;
    }

    if (activeNav === "inbox") {
      return (
        <SplitSurface
          {...splitProps}
          main={<InboxPage selected={selectedMemory} onSelect={selectMemory} />}
          inspector={<MemoryInspector memory={selectedMemory} onOpenDetail={() => setDetailMode("memory")} {...inspectorControls} />}
        />
      );
    }

    if (activeNav === "library") {
      return (
        <SplitSurface
          {...splitProps}
          main={<LibraryPage selected={selectedMemory} onSelect={selectMemory} />}
          inspector={<MemoryInspector memory={selectedMemory} onOpenDetail={() => setDetailMode("memory")} libraryMode {...inspectorControls} />}
        />
      );
    }

    if (activeNav === "project") {
      return (
        <SplitSurface
          {...splitProps}
          main={<ProjectPage />}
          inspector={<ProjectInspector onOpenDetail={() => setDetailMode("project")} {...inspectorControls} />}
        />
      );
    }

    if (activeNav === "maintenance") {
      return (
        <SplitSurface
          {...splitProps}
          main={<MaintenancePage selected={selectedMaintenance} onSelect={selectMaintenance} />}
          inspector={<MaintenanceInspector item={selectedMaintenance} onOpenDetail={() => setDetailMode("maintenance")} {...inspectorControls} />}
        />
      );
    }

    return <SettingsPage />;
  }, [activeNav, detailMode, inspectorOpen, inspectorWidth, selectedMaintenance, selectedMemory]);

  return (
    <AppShell activeNav={activeNav} shellMode={detailMode ? "detail" : "split"} onSelectNav={openNav}>
      {content}
    </AppShell>
  );
}
