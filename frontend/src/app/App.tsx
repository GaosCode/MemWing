import { useMemo, useState } from "react";
import { RefreshCcw } from "lucide-react";
import "./controlPlaneState.css";
import { AppShell, type TopbarScopeOptions } from "./AppShell";
import { maintenanceKey, useControlPlaneData } from "./useControlPlaneData";
import { controlScope } from "./controlScope";
import { Button, SplitSurface } from "../shared/components/ui";
import type { ControlPageDto, ControlScopeParams } from "../api/generated/controlPlane";
import type { ManualMemoryInput } from "../shared/api/controlPlaneClient";
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
  const [scope, setScope] = useState<ControlScopeParams>(() => ({ ...controlScope }));
  const [globalSearchQuery, setGlobalSearchQuery] = useState("");
  const control = useControlPlaneData(scope);

  const visibleMemories = useMemo(
    () => filterMemoriesBySearch(control.memories, globalSearchQuery),
    [control.memories, globalSearchQuery],
  );
  const visibleMaintenanceItems = useMemo(
    () => filterMaintenanceBySearch(control.maintenanceItems, globalSearchQuery),
    [control.maintenanceItems, globalSearchQuery],
  );
  const scopeOptions = useMemo(
    () => buildScopeOptions(scope, control.memories, control.selectedPage, control.settings?.project_memory_space_id ?? null),
    [control.memories, control.selectedPage, control.settings?.project_memory_space_id, scope],
  );
  const searchResultCount = useMemo(() => {
    if (globalSearchQuery.trim().length === 0) {
      return null;
    }
    return visibleMemories.length
      + visibleMaintenanceItems.length
      + (control.selectedPage !== null && matchesPageSearch(control.selectedPage, globalSearchQuery) ? 1 : 0);
  }, [control.selectedPage, globalSearchQuery, visibleMaintenanceItems.length, visibleMemories.length]);

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
          sourceEventDetails={control.sourceEventDetails}
          onLoadSourceEvent={control.loadSourceEventDetail}
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
          main={<InboxPage memories={visibleMemories} selected={control.selectedMemory} onSelect={selectMemory} />}
          inspector={<MemoryInspector memory={control.selectedMemory} onOpenDetail={() => setDetailMode("memory")} onLifecycleAction={control.runMemoryLifecycleAction} {...inspectorControls} />}
        />
      );
    }

    if (activeNav === "library") {
      return (
        <SplitSurface
          {...splitProps}
          main={<LibraryPage memories={visibleMemories} selected={control.selectedMemory} onSelect={selectMemory} onCreateMemory={submitManualMemory} />}
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
              memories={visibleMemories}
              onSelectMemory={selectMemory}
              onRebuildPage={control.runPageRebuild}
              onEditPage={control.runPageEdit}
              onRestorePageVersion={control.runPageRestore}
              sourceEventDetails={control.sourceEventDetails}
              onLoadSourceEvent={control.loadSourceEventDetail}
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
              items={visibleMaintenanceItems}
              memories={visibleMemories}
              selected={control.selectedMaintenance}
              onSelect={selectMaintenance}
              onAction={control.runMaintenanceAction}
              onRefreshData={() => control.refreshControlPlane({ showLoading: false })}
              onMemoryLifecycleAction={control.runMemoryLifecycleAction}
            />
          }
          inspector={<MaintenanceInspector item={control.selectedMaintenance} onOpenDetail={() => setDetailMode("maintenance")} onAction={control.runMaintenanceAction} {...inspectorControls} />}
        />
      );
    }

    return <SettingsPage settings={control.settings} integrations={control.integrations} onRefresh={() => void control.refreshSettings()} />;
  }, [activeNav, control, detailMode, inspectorOpen, inspectorWidth, visibleMaintenanceItems, visibleMemories]);

  async function submitManualMemory(input: ManualMemoryInput) {
    await control.runManualMemoryCreate(input);
    setActiveNav("library");
    setDetailMode(null);
    setInspectorOpen(false);
    setGlobalSearchQuery(input.title);
  }

  return (
    <AppShell
      activeNav={activeNav}
      shellMode={detailMode ? "detail" : "split"}
      scope={scope}
      scopeOptions={scopeOptions}
      searchQuery={globalSearchQuery}
      searchResultCount={searchResultCount}
      onSelectNav={openNav}
      onRefresh={control.refreshControlPlane}
      onScopeChange={setScope}
      onSearchQueryChange={setGlobalSearchQuery}
    >
      {content}
    </AppShell>
  );
}

function buildScopeOptions(
  scope: ControlScopeParams,
  memories: MemoryItem[],
  selectedPage: ControlPageDto | null,
  settingsWorkspaceId: string | null,
): TopbarScopeOptions {
  return {
    workspaces: uniqueText([
      scope.project_memory_space_id,
      settingsWorkspaceId,
      selectedPage?.project_memory_space_id ?? null,
    ]),
    groups: uniqueText([
      ...memories.map((memory) => memory.groupId),
      selectedPage?.group_id ?? null,
    ]),
    threads: uniqueText([
      ...memories.map((memory) => memory.threadId),
      selectedPage?.thread_id ?? null,
    ]),
  };
}

function filterMemoriesBySearch(memories: MemoryItem[], query: string): MemoryItem[] {
  if (query.trim().length === 0) {
    return memories;
  }
  return memories.filter((memory) => matchesSearch(query, [
    memory.id,
    memory.title,
    memory.type,
    memory.source,
    memory.sourceState,
    memory.groupId,
    memory.threadId,
    memory.lastSeen,
    memory.status,
    memory.reason,
    ...memory.flags,
    ...memory.sourceEventIds,
  ]));
}

function filterMaintenanceBySearch(items: MaintenanceItem[], query: string): MaintenanceItem[] {
  if (query.trim().length === 0) {
    return items;
  }
  return items.filter((item) => matchesSearch(query, [
    item.id,
    item.actionKind,
    item.jobKind ?? null,
    item.type,
    item.title,
    item.source,
    item.reason,
    item.state,
    item.updated,
    item.severity,
    ...(item.sourceEventIds ?? []),
    ...(item.memoryItemIds ?? []),
  ]));
}

function matchesPageSearch(page: ControlPageDto, query: string) {
  return matchesSearch(query, [
    page.id,
    page.title,
    page.brief,
    page.project_memory_space_id,
    page.group_id,
    page.thread_id,
    page.scope_id,
    page.scope_type,
    page.updated_at,
    ...page.source_event_ids,
    ...page.linked_memory_item_ids,
    ...page.open_questions,
    ...page.next_steps,
    ...page.topics.flatMap((topic) => [topic.title, topic.summary]),
  ]);
}

function matchesSearch(query: string, values: Array<string | null>) {
  const normalizedQuery = normalizeSearch(query);
  return values.some((value) => value !== null && normalizeSearch(value).includes(normalizedQuery));
}

function normalizeSearch(value: string) {
  return value.trim().toLocaleLowerCase();
}

function uniqueText(values: Array<string | null>) {
  return [...new Set(values.filter((value): value is string => value !== null && value.trim().length > 0))];
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
