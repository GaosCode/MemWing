import { useMemo, useState } from "react";
import { Check, MoreHorizontal, Pause, Play, RotateCcw } from "lucide-react";
import { Button, IconButton, Metric, PageHeader, ScrollableTabs } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
import type { MemoryLifecycleAction } from "../../api/generated/controlPlane";
import type { MaintenanceItem, MemoryItem } from "../../shared/types/entities";
import { ForgettingReview } from "./MaintenanceForgetting";
import {
  filterMaintenanceItems,
  maintenanceItemKey,
  NeedsAttention,
  PushCandidates,
  RecentFailures,
  ReviewQueue,
  type MaintenanceAction,
} from "./MaintenanceQueues";
import { JobHistory, WorkerHealth } from "./MaintenanceWorkers";

const maintenanceTabs = ["Overview", "Needs Attention", "Review Queue", "Recent Failures", "Push Candidates", "Forgetting Review", "Worker Health", "Job History"];

export function MaintenancePage({
  items,
  memories,
  selected,
  onSelect,
  onAction,
  onMemoryLifecycleAction,
}: {
  items: MaintenanceItem[];
  memories: MemoryItem[];
  selected: MaintenanceItem;
  onSelect: (item: MaintenanceItem) => void;
  onAction: (item: MaintenanceItem, action: MaintenanceAction) => Promise<void>;
  onMemoryLifecycleAction: (memory: MemoryItem, action: MemoryLifecycleAction, reason: string) => Promise<void>;
}) {
  const { dictionary } = useI18n();
  const [activeTab, setActiveTab] = useState("Needs Attention");
  const [activeChip, setActiveChip] = useState("All");
  const [queuePaused, setQueuePaused] = useState(false);
  const [taskActions, setTaskActions] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState(dictionary.maintenance.noticeLive);
  const [updatingKey, setUpdatingKey] = useState<string | null>(null);
  const filteredItems = useMemo(() => filterMaintenanceItems(items, activeChip), [activeChip, items]);
  const failedItems = items.filter((item) => item.state === "Failed");
  const reviewItems = items.filter((item) => item.type === "Review" || item.state === "Review Pending");
  const pushItems = items.filter((item) => item.actionKind === "push_candidate");

  function recordAction(key: string, message: string) {
    setTaskActions((current) => ({ ...current, [key]: message }));
    setNotice(message);
  }

  function runBackendAction(item: MaintenanceItem, action: MaintenanceAction) {
    const key = maintenanceItemKey(item);
    setUpdatingKey(key);
    recordAction(key, "Sending to backend");
    void onAction(item, action)
      .then(() => recordAction(key, "Backend action completed"))
      .catch((error) => recordAction(key, error instanceof Error ? error.message : "MemWing API request failed"))
      .finally(() => setUpdatingKey(null));
  }

  return (
    <>
      <PageHeader
        title={dictionary.maintenance.title}
        subtitle={dictionary.maintenance.subtitle}
        actions={
          <>
            <Button icon={queuePaused ? Play : Pause} label={queuePaused ? dictionary.actions.resumeQueue : dictionary.actions.pauseQueue} onClick={() => {
              setQueuePaused((value) => !value);
              setNotice(queuePaused ? dictionary.maintenance.queueResumed : dictionary.maintenance.queuePaused);
            }} />
            <Button icon={RotateCcw} label={dictionary.actions.retryFailed} onClick={() => failedItems.forEach((item) => runBackendAction(item, "retry"))} disabled={failedItems.length === 0 || updatingKey !== null} />
            <IconButton label={dictionary.common.more} icon={MoreHorizontal} onClick={() => setNotice("Maintenance command menu opened")} />
          </>
        }
      />

      <div className="status-strip">
        <Metric label={dictionary.maintenance.metrics.queue} value={queuePaused ? dictionary.status.queue.Paused : dictionary.status.queue.Running} tone={queuePaused ? "orange" : "green"} />
        <Metric label={dictionary.maintenance.metrics.needsReview} value={String(reviewItems.length)} tone="orange" />
        <Metric label={dictionary.maintenance.metrics.failedJobs} value={String(failedItems.length)} tone={failedItems.length > 0 ? "red" : "green"} />
        <Metric label={dictionary.maintenance.metrics.workersHealthy} value={`${Math.max(items.length - failedItems.length, 0)} / ${items.length}`} tone={failedItems.length > 0 ? "orange" : "green"} />
        <Metric label={dictionary.maintenance.metrics.lastRun} value={items[0]?.updated ?? "none"} />
      </div>

      <ScrollableTabs label="Maintenance tabs" activeTab={activeTab} tabs={maintenanceTabs} onSelect={setActiveTab} />
      <div className="notice-row"><Check size={15} />{notice}</div>

      {activeTab === "Overview" ? <MaintenanceOverview items={items} memories={memories} onOpen={setActiveTab} /> : null}
      {activeTab === "Needs Attention" ? (
        <>
          <NeedsAttention items={filteredItems} selected={selected} activeChip={activeChip} actions={taskActions} onSelect={onSelect} onChip={setActiveChip} />
          <WorkerHealth compact items={items} />
        </>
      ) : null}
      {activeTab === "Review Queue" ? <ReviewQueue items={reviewItems} actions={taskActions} onSelect={onSelect} /> : null}
      {activeTab === "Recent Failures" ? <RecentFailures items={failedItems} actions={taskActions} onSelect={onSelect} onAction={runBackendAction} /> : null}
      {activeTab === "Push Candidates" ? <PushCandidates items={pushItems} actions={taskActions} onSelect={onSelect} onAction={runBackendAction} /> : null}
      {activeTab === "Forgetting Review" ? (
        <ForgettingReview
          items={items}
          memories={memories}
          onSelect={onSelect}
          onRefresh={() => setNotice("Decay scores refreshed from loaded memory list")}
          onDecision={recordAction}
          onMemoryLifecycleAction={onMemoryLifecycleAction}
          decisions={taskActions}
        />
      ) : null}
      {activeTab === "Worker Health" ? <WorkerHealth items={items} onAction={recordAction} /> : null}
      {activeTab === "Job History" ? <JobHistory items={items} /> : null}
    </>
  );
}

function MaintenanceOverview({
  items,
  memories,
  onOpen,
}: {
  items: MaintenanceItem[];
  memories: MemoryItem[];
  onOpen: (tab: string) => void;
}) {
  const failed = items.filter((item) => item.state === "Failed").length;
  const forgetting = memories.filter((memory) => memory.forgetting.curveState !== "retained").length;
  const push = items.filter((item) => item.actionKind === "push_candidate").length;
  const panels = [
    { title: "Needs Attention", value: String(items.length), body: "Backend maintenance jobs and candidates for this scope.", tab: "Needs Attention", tone: "green" as const },
    { title: "Forgetting Review", value: String(forgetting), body: "Loaded memories with non-retained forgetting curve state.", tab: "Forgetting Review", tone: forgetting > 0 ? "orange" as const : "green" as const },
    { title: "Push Candidates", value: String(push), body: "Validated candidates returned by Control Plane maintenance.", tab: "Push Candidates", tone: "green" as const },
    { title: "Worker Health", value: failed > 0 ? `${failed} failed` : "healthy", body: "Projected from graph/outbox job state.", tab: "Worker Health", tone: failed > 0 ? "orange" as const : "green" as const },
  ];

  return (
    <div className="overview-grid">
      {panels.map((panel) => (
        <button key={panel.title} className="overview-panel overview-panel--action" type="button" onClick={() => onOpen(panel.tab)}>
          <span>{panel.title}</span>
          <strong>{panel.value}</strong>
          <p>{panel.body}</p>
        </button>
      ))}
    </div>
  );
}
