import { useEffect, useMemo, useState } from "react";
import { controlMaintenanceToItems } from "../api/mappers/controlPlane";
import { memoryListItemToViewModel } from "../api/mappers/memoryList";
import type { ManualMemoryInput, MemoryEditInput, PageEditInput } from "../shared/api/controlPlaneClient";
import {
  approvePushCandidate,
  createManualMemory,
  editControlPage,
  editMemory,
  getControlIntegrations,
  getControlMaintenance,
  getControlMemory,
  getControlPage,
  getControlSettings,
  getControlSourceEvent,
  listControlMemories,
  listControlPages,
  mutateMemoryLifecycle,
  rebuildControlPage,
  restoreControlPageVersion,
  retryControlJob,
  sendFeishuPushCandidate,
  skipPushCandidate,
} from "../shared/api/controlPlaneClient";
import type {
  ControlIntegrationsResponseDto,
  ControlPageDetailDto,
  ControlPageDto,
  ControlSettingsDto,
  ControlSourceEventDetailDto,
  ControlScopeParams,
  MemoryDetailDto,
  MemoryLifecycleAction,
} from "../api/generated/controlPlane";
import type { MaintenanceItem, MemoryItem } from "../shared/types/entities";
import { controlScope } from "./controlScope";

export type MaintenanceBackendAction = "retry" | "approve" | "skip" | "send";

export function maintenanceKey(item: MaintenanceItem) {
  return `${item.actionKind}:${item.id}`;
}

type RefreshOptions = {
  showLoading?: boolean;
};

export function useControlPlaneData(scope: ControlScopeParams = controlScope) {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoryDetails, setMemoryDetails] = useState<Record<string, MemoryDetailDto>>({});
  const [maintenanceItems, setMaintenanceItems] = useState<MaintenanceItem[]>([]);
  const [pages, setPages] = useState<ControlPageDto[]>([]);
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [selectedPageDetail, setSelectedPageDetail] = useState<ControlPageDetailDto | null>(null);
  const [sourceEventDetails, setSourceEventDetails] = useState<Record<string, ControlSourceEventDetailDto>>({});
  const [settings, setSettings] = useState<ControlSettingsDto | null>(null);
  const [integrations, setIntegrations] = useState<ControlIntegrationsResponseDto | null>(null);
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null);
  const [selectedMaintenance, setSelectedMaintenance] = useState<MaintenanceItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    setMemoryDetails({});
    setSourceEventDetails({});
    void refreshControlPlane();
  }, [scope.group_id, scope.project_memory_space_id, scope.shared_group_id, scope.thread_id]);

  useEffect(() => {
    if (selectedMemoryId !== null && memoryDetails[selectedMemoryId] === undefined) {
      void loadMemoryDetail(selectedMemoryId);
    }
  }, [memoryDetails, selectedMemoryId]);

  const selectedMemory = useMemo(
    () => memories.find((memory) => memory.id === selectedMemoryId) ?? memories[0] ?? null,
    [memories, selectedMemoryId],
  );
  const selectedPage = useMemo(
    () => pages.find((page) => page.id === selectedPageId) ?? pages[0] ?? null,
    [pages, selectedPageId],
  );

  return {
    memories,
    memoryDetails,
    maintenanceItems,
    selectedMaintenance,
    selectedMemory,
    selectedPage,
    selectedPageDetail,
    sourceEventDetails,
    settings,
    integrations,
    loading,
    loadError,
    setSelectedMemoryId,
    setSelectedMaintenance,
    refreshControlPlane,
    refreshSettings,
    runMemoryLifecycleAction,
    runMemoryEdit,
    runPageRebuild,
    runPageEdit,
    runPageRestore,
    runMaintenanceAction,
    runManualMemoryCreate,
    loadSourceEventDetail,
  };

  async function refreshControlPlane(options: RefreshOptions = {}) {
    const showLoading = options.showLoading ?? true;
    if (showLoading) {
      setLoading(true);
    }
      setLoadError(null);
    try {
      const [memoryList, maintenance, pageList, nextSettings, nextIntegrations] = await Promise.all([
        listControlMemories(scope),
        getControlMaintenance(scope),
        listControlPages(scope),
        getControlSettings(scope),
        getControlIntegrations(),
      ]);
      const nextMemories = memoryList.items.map(memoryListItemToViewModel);
      const nextMaintenanceItems = controlMaintenanceToItems(maintenance);
      const nextPage = pageList.items.find((page) => page.id === selectedPageId) ?? pageList.items[0] ?? null;
      const nextPageDetail = nextPage !== null ? await getControlPage(scope, nextPage.id) : null;
      setMemories(nextMemories);
      setMaintenanceItems(nextMaintenanceItems);
      setPages(pageList.items);
      setSettings(nextSettings);
      setIntegrations(nextIntegrations);
      setSelectedMemoryId((current) => (
        current !== null && nextMemories.some((memory) => memory.id === current)
          ? current
          : nextMemories[0]?.id ?? null
      ));
      setSelectedMaintenance((current) => (
        current !== null && nextMaintenanceItems.some((item) => maintenanceKey(item) === maintenanceKey(current))
          ? current
          : nextMaintenanceItems[0] ?? null
      ));
      setSelectedPageId((current) => (
        current !== null && pageList.items.some((page) => page.id === current)
          ? current
          : nextPage?.id ?? null
      ));
      setSelectedPageDetail(nextPageDetail);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "MemWing API request failed");
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }

  async function runMemoryLifecycleAction(
    memory: MemoryItem,
    action: MemoryLifecycleAction,
    reason: string,
  ) {
    const detail = await mutateMemoryLifecycle(scope, memory.id, action, reason);
    const nextMemory = memoryListItemToViewModel(detail.item);
    setMemoryDetails((current) => ({ ...current, [memory.id]: detail }));
    replaceMemory(nextMemory);
  }

  async function runMemoryEdit(memory: MemoryItem, input: MemoryEditInput, reason: string) {
    const detail = await editMemory(scope, memory.id, input, reason);
    const nextMemory = memoryListItemToViewModel(detail.item);
    setMemoryDetails((current) => ({ ...current, [memory.id]: detail }));
    replaceMemory(nextMemory);
  }

  function replaceMemory(nextMemory: MemoryItem) {
    setMemories((current) => current.map((item) => item.id === nextMemory.id ? nextMemory : item));
    setSelectedMemoryId(nextMemory.id);
  }

  async function runPageRebuild(page: ControlPageDto) {
    const detail = await rebuildControlPage(scope, page.id, "frontend manual page rebuild");
    replacePageDetail(detail);
  }

  async function runPageEdit(page: ControlPageDto, input: PageEditInput, reason: string) {
    const detail = await editControlPage(scope, page.id, input, reason);
    replacePageDetail(detail);
  }

  async function runPageRestore(page: ControlPageDto, version: number) {
    const detail = await restoreControlPageVersion(scope, page.id, version, "frontend page version restore");
    replacePageDetail(detail);
  }

  function replacePageDetail(detail: ControlPageDetailDto) {
    setPages((current) => current.map((page) => page.id === detail.page.id ? detail.page : page));
    setSelectedPageId(detail.page.id);
    setSelectedPageDetail(detail);
  }

  async function runMaintenanceAction(item: MaintenanceItem, action: MaintenanceBackendAction) {
    if (item.actionKind === "job" && action === "retry") {
      await retryControlJob(scope, item.id, item.jobKind ?? "", "frontend retry failed maintenance job");
      await refreshMaintenance();
      return;
    }
    if (item.actionKind === "push_candidate" && action === "approve") {
      await approvePushCandidate(scope, item.id, "frontend approve push candidate");
      await refreshMaintenance();
      return;
    }
    if (item.actionKind === "push_candidate" && action === "skip") {
      await skipPushCandidate(scope, item.id, "frontend skip push candidate");
      await refreshMaintenance();
      return;
    }
    if (item.actionKind === "push_candidate" && action === "send") {
      await sendFeishuPushCandidate(scope, item.id, "frontend send approved push candidate");
      await refreshMaintenance();
      return;
    }
    throw new Error("This maintenance action is not supported by the backend contract.");
  }

  async function refreshMaintenance() {
    const maintenance = await getControlMaintenance(scope);
    const nextMaintenanceItems = controlMaintenanceToItems(maintenance);
    setMaintenanceItems(nextMaintenanceItems);
    setSelectedMaintenance((current) => {
      if (current === null) {
        return nextMaintenanceItems[0] ?? null;
      }
      return nextMaintenanceItems.find((item) => maintenanceKey(item) === maintenanceKey(current)) ?? nextMaintenanceItems[0] ?? null;
    });
  }

  async function refreshSettings() {
    const [nextSettings, nextIntegrations] = await Promise.all([
      getControlSettings(scope),
      getControlIntegrations(),
    ]);
    setSettings(nextSettings);
    setIntegrations(nextIntegrations);
  }

  async function loadMemoryDetail(memoryId: string) {
    try {
      const detail = await getControlMemory(scope, memoryId);
      setMemoryDetails((current) => ({ ...current, [memoryId]: detail }));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "MemWing memory detail request failed");
    }
  }

  async function loadSourceEventDetail(sourceEventId: string) {
    if (sourceEventDetails[sourceEventId] !== undefined) {
      return sourceEventDetails[sourceEventId];
    }
    const detail = await getControlSourceEvent(scope, sourceEventId);
    setSourceEventDetails((current) => ({ ...current, [sourceEventId]: detail }));
    return detail;
  }

  async function runManualMemoryCreate(input: ManualMemoryInput) {
    await createManualMemory(scope, input);
    await refreshControlPlane({ showLoading: false });
  }
}
