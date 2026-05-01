import { useState } from "react";
import { Check, Clock3, Eye, FileText, MoreHorizontal, Pause, Play, RotateCcw, ShieldCheck, TrendingDown } from "lucide-react";
import { maintenanceItems, memories } from "../../shared/api/mockData";
import { Button, IconButton, Metric, PageHeader, ScrollableTabs, StatusPill, StrengthMeter } from "../../shared/components/ui";
import { severityTone } from "../../shared/design-system/status";
import { curveStateLabel, maintenanceStateLabel } from "../../shared/i18n/formatters";
import { useI18n } from "../../shared/i18n";
import type { LocaleDictionary } from "../../shared/i18n/locales/zh-CN";
import type { MaintenanceItem, MemoryItem } from "../../shared/types/entities";
import { jobHistoryRows, workerHealthRows } from "./maintenanceData";

const maintenanceTabs = ["Overview", "Needs Attention", "Review Queue", "Recent Failures", "Push Candidates", "Forgetting Review", "Worker Health", "Job History"];
const chips = ["All", "Failed", "Review", "Push", "Forgetting"];

function chipLabel(dictionary: LocaleDictionary, chip: string) {
  const chipMap: Record<string, string> = {
    All: dictionary.maintenance.chips.all,
    Failed: dictionary.maintenance.chips.failed,
    Review: dictionary.maintenance.chips.review,
    Push: dictionary.maintenance.chips.push,
    Forgetting: dictionary.maintenance.chips.forgetting,
  };
  return chipMap[chip] ?? chip;
}

export function MaintenancePage({
  selected,
  onSelect,
}: {
  selected: MaintenanceItem;
  onSelect: (item: MaintenanceItem) => void;
}) {
  const { dictionary } = useI18n();
  const [activeTab, setActiveTab] = useState("Needs Attention");
  const [activeChip, setActiveChip] = useState("All");
  const [queuePaused, setQueuePaused] = useState(false);
  const [taskActions, setTaskActions] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState(dictionary.maintenance.noticeLive);

  function itemKey(item: MaintenanceItem) {
    return `${item.type}:${item.title}:${item.updated}`;
  }

  function recordAction(key: string, message: string) {
    setTaskActions((current) => ({ ...current, [key]: message }));
    setNotice(message);
  }

  const filteredItems = maintenanceItems.filter((item) => {
    if (activeChip === "All") {
      return true;
    }
    if (activeChip === "Failed") {
      return item.state === "Failed";
    }
    return item.type === activeChip;
  });

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
            <Button icon={RotateCcw} label={dictionary.actions.retryFailed} onClick={() => setNotice(dictionary.maintenance.retryScheduled)} />
            <IconButton label={dictionary.common.more} icon={MoreHorizontal} onClick={() => setNotice("Maintenance command menu opened")} />
          </>
        }
      />

      <div className="status-strip">
        <Metric label={dictionary.maintenance.metrics.queue} value={queuePaused ? dictionary.status.queue.Paused : dictionary.status.queue.Running} tone={queuePaused ? "orange" : "green"} />
        <Metric label={dictionary.maintenance.metrics.needsReview} value="7" tone="orange" />
        <Metric label={dictionary.maintenance.metrics.failedJobs} value="2" tone="red" />
        <Metric label={dictionary.maintenance.metrics.workersHealthy} value="4 / 5" tone="green" />
        <Metric label={dictionary.maintenance.metrics.lastRun} value="2026-04-27 11:32" />
      </div>

      <ScrollableTabs
        label="Maintenance tabs"
        activeTab={activeTab}
        tabs={maintenanceTabs}
        onSelect={setActiveTab}
      />

      <div className="notice-row"><Check size={15} />{notice}</div>

      {activeTab === "Overview" ? <MaintenanceOverview onOpen={setActiveTab} /> : null}
      {activeTab === "Needs Attention" ? (
        <NeedsAttention items={filteredItems} selected={selected} activeChip={activeChip} actions={taskActions} onSelect={onSelect} onChip={setActiveChip} />
      ) : null}
      {activeTab === "Review Queue" ? (
        <ReviewQueue
          items={maintenanceItems.filter((item) => item.type === "Review")}
          actions={taskActions}
          onSelect={onSelect}
          onAction={(item, action) => recordAction(itemKey(item), `${action}: ${item.title}`)}
        />
      ) : null}
      {activeTab === "Recent Failures" ? (
        <RecentFailures
          items={maintenanceItems.filter((item) => item.state === "Failed")}
          actions={taskActions}
          onSelect={onSelect}
          onAction={(item, action) => recordAction(itemKey(item), `${action}: ${item.title}`)}
        />
      ) : null}
      {activeTab === "Push Candidates" ? (
        <PushCandidates
          items={maintenanceItems.filter((item) => item.type === "Push")}
          actions={taskActions}
          onSelect={onSelect}
          onAction={(item, action) => recordAction(itemKey(item), `${action}: ${item.title}`)}
        />
      ) : null}
      {activeTab === "Forgetting Review" ? <ForgettingReview onSelect={onSelect} onRefresh={() => setNotice("Decay scores refreshed for forgetting review")} onDecision={recordAction} decisions={taskActions} /> : null}
      {activeTab === "Worker Health" ? <WorkerHealth onAction={recordAction} /> : null}
      {activeTab === "Job History" ? <JobHistory /> : null}
    </>
  );
}

function MaintenanceOverview({ onOpen }: { onOpen: (tab: string) => void }) {
  const panels = [
    { title: "Needs Attention", value: "7", body: "Review conflict, stale wording, and forgetting candidates.", tab: "Needs Attention", tone: "green" as const },
    { title: "Forgetting Review", value: "2", body: "Memories are below review threshold and need retention decisions.", tab: "Forgetting Review", tone: "orange" as const },
    { title: "Push Candidates", value: "4", body: "Validated memories waiting for project memory push.", tab: "Push Candidates", tone: "green" as const },
    { title: "Worker Health", value: "4 / 5", body: "PushWorker is failed; other workers are healthy.", tab: "Worker Health", tone: "orange" as const },
  ];

  return (
    <div className="overview-grid">
      {panels.map((panel) => (
        <button key={panel.title} className="overview-panel overview-panel--action" type="button" onClick={() => onOpen(panel.tab)}>
          <span>{panel.title}</span>
          <strong>{panel.value}</strong>
          <p>{panel.body}</p>
          <StatusPill label={`Open ${panel.tab}`} tone={panel.tone} />
        </button>
      ))}
    </div>
  );
}

function NeedsAttention({
  items,
  selected,
  activeChip,
  actions,
  onSelect,
  onChip,
}: {
  items: MaintenanceItem[];
  selected: MaintenanceItem;
  activeChip: string;
  actions: Record<string, string>;
  onSelect: (item: MaintenanceItem) => void;
  onChip: (chip: string) => void;
}) {
  const { dictionary } = useI18n();
  return (
    <>
      <div className="section-toolbar">
        <h2>{dictionary.maintenance.tabs.needsAttention}</h2>
        <div className="chip-row">
          {chips.map((chip) => (
            <button key={chip} className={activeChip === chip ? "is-active" : ""} type="button" onClick={() => onChip(chip)}>{chipLabel(dictionary, chip)}</button>
          ))}
        </div>
      </div>
      <MaintenanceTable items={items} selected={selected} actions={actions} onSelect={onSelect} />
      <WorkerHealth compact />
    </>
  );
}

function ReviewQueue({
  items,
  actions,
  onSelect,
  onAction,
}: {
  items: MaintenanceItem[];
  actions: Record<string, string>;
  onSelect: (item: MaintenanceItem) => void;
  onAction: (item: MaintenanceItem, action: string) => void;
}) {
  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Review Queue</h2>
          <p className="section-subtitle">Confirm, request changes, or open evidence before memories leave review pending state.</p>
        </div>
        <span className="muted-count">{items.length} items</span>
      </div>
      <MaintenanceTable items={items} actions={actions} onSelect={onSelect} />
      <div className="action-list action-list--maintenance">
        {items.map((item) => (
          <section key={item.title} className="action-list-row action-list-row--review-queue">
            <StatusPill label={item.state} tone="orange" />
            <span>{item.title}</span>
            <strong>{item.reason}</strong>
            <button type="button" onClick={() => onSelect(item)}>inspect</button>
            <button type="button" onClick={() => onAction(item, "Confirmed review")}>confirm</button>
            <button type="button" onClick={() => onAction(item, "Changes requested")}>request changes</button>
          </section>
        ))}
      </div>
    </>
  );
}

function RecentFailures({
  items,
  actions,
  onSelect,
  onAction,
}: {
  items: MaintenanceItem[];
  actions: Record<string, string>;
  onSelect: (item: MaintenanceItem) => void;
  onAction: (item: MaintenanceItem, action: string) => void;
}) {
  const { dictionary } = useI18n();
  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Recent Failures</h2>
          <p className="section-subtitle">Failed jobs stay blocked until linked evidence and conflict state are reviewed.</p>
        </div>
        <Button icon={RotateCcw} label="Retry Failed" onClick={() => items.forEach((item) => onAction(item, "Retry scheduled"))} />
      </div>
      <MaintenanceTable items={items} actions={actions} onSelect={onSelect} />
      <div className="failure-recovery">
        {items.map((item) => (
          <section key={item.title} className="failure-card">
            <StatusPill label={dictionary.status.queue.Blocked} tone="red" />
            <strong>{item.title}</strong>
            <p>{item.reason}. Review audit before retrying the worker.</p>
            <div className="inline-action-row">
              <Button primary icon={RotateCcw} label={dictionary.actions.retryJob} onClick={() => onAction(item, "Retry scheduled after review")} />
              <Button icon={ShieldCheck} label={dictionary.actions.openAudit} onClick={() => onAction(item, "Audit opened")} />
              <Button icon={Eye} label={dictionary.actions.viewSource} onClick={() => onSelect(item)} />
            </div>
          </section>
        ))}
      </div>
    </>
  );
}

function PushCandidates({
  items,
  actions,
  onSelect,
  onAction,
}: {
  items: MaintenanceItem[];
  actions: Record<string, string>;
  onSelect: (item: MaintenanceItem) => void;
  onAction: (item: MaintenanceItem, action: string) => void;
}) {
  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Push Candidates</h2>
          <p className="section-subtitle">Validated memories waiting to be promoted into Project Memory with source-backed confidence.</p>
        </div>
        <span className="muted-count">{items.length} open</span>
      </div>
      <div className="push-candidate-summary">
        <section>
          <span>Ready to push</span>
          <strong>{items.length}</strong>
          <p>All candidates have at least 3 linked sources and no redaction blockers.</p>
        </section>
        <section>
          <span>Target</span>
          <strong>Project Memory</strong>
          <p>Approved pushes become rebuild inputs instead of overwriting the current page.</p>
        </section>
        <section>
          <span>Safety gate</span>
          <strong>Review required</strong>
          <p>Approvals are recorded locally until backend persistence lands.</p>
        </section>
      </div>
      <div className="action-list action-list--maintenance">
        {items.map((item) => (
          <section key={item.title} className="action-list-row action-list-row--push-candidate">
            <StatusPill label={actions[`${item.type}:${item.title}:${item.updated}`] ?? item.type} tone="green" />
            <span>{item.title}</span>
            <strong>{item.reason}</strong>
            <span>{item.source}</span>
            <button type="button" onClick={() => onSelect(item)}>inspect</button>
            <button type="button" onClick={() => onAction(item, "Push approved")}>approve push</button>
            <button type="button" onClick={() => onAction(item, "Push skipped")}>skip</button>
          </section>
        ))}
      </div>
    </>
  );
}

function MaintenanceTable({
  items,
  selected,
  actions,
  onSelect,
}: {
  items: MaintenanceItem[];
  selected?: MaintenanceItem;
  actions?: Record<string, string>;
  onSelect: (item: MaintenanceItem) => void;
}) {
  const { dictionary } = useI18n();
  return (
    <div className="maintenance-table">
      <div className="maintenance-row maintenance-row--head">
        <span>{dictionary.maintenance.table.type}</span>
        <span>{dictionary.maintenance.table.item}</span>
        <span>{dictionary.maintenance.table.source}</span>
        <span>{dictionary.maintenance.table.reason}</span>
        <span>{dictionary.maintenance.table.state}</span>
        <span>{dictionary.maintenance.table.updated}</span>
      </div>
      {items.map((item) => (
        <button
          key={`${item.title}-${item.updated}`}
          className={`maintenance-row ${selected?.title === item.title ? "is-selected" : ""}`}
          onClick={() => onSelect(item)}
        >
          <StatusPill label={item.type} tone={severityTone[item.severity]} />
          <span>{item.title}</span>
          <span>{item.source}</span>
          <span>{item.reason}</span>
          <span><StatusPill label={actions?.[`${item.type}:${item.title}:${item.updated}`] ?? maintenanceStateLabel(dictionary, item.state)} tone={item.state === "Failed" ? "red" : item.state === "Open" ? "green" : "orange"} /></span>
          <span>{item.updated}</span>
        </button>
      ))}
    </div>
  );
}

function ForgettingReview({
  onSelect,
  onRefresh,
  onDecision,
  decisions,
}: {
  onSelect: (item: MaintenanceItem) => void;
  onRefresh: () => void;
  onDecision: (key: string, decision: string) => void;
  decisions: Record<string, string>;
}) {
  const { dictionary } = useI18n();
  const forgettingItems = maintenanceItems.filter((item) => item.type === "Forgetting" || item.state === "Ready to forget");
  const fadingMemories = memories.filter((memory) => memory.forgetting.curveState !== "stable").slice(0, 4);
  const decayPoints = [
    { day: "D0", score: 0.92 },
    { day: "D7", score: 0.78 },
    { day: "D14", score: 0.61 },
    { day: "D21", score: 0.48 },
    { day: "D30", score: 0.31 },
  ];
  const decayPolyline = decayPoints
    .map((point, index) => `${18 + index * 71},${18 + (1 - point.score) * 104}`)
    .join(" ");

  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Forgetting Curve Review</h2>
          <p className="section-subtitle">Review decay score, next review, and retention reason before memory is forgotten.</p>
        </div>
        <Button icon={TrendingDown} label={dictionary.actions.refreshDecayScores} onClick={onRefresh} />
      </div>
      <div className="curve-review-grid">
        <section className="curve-panel">
          <h3>Decay thresholds</h3>
          <div className="curve-line" aria-hidden="true">
            <svg viewBox="0 0 320 150" role="img" aria-label="Decay score trend">
              <line className="curve-grid-line" x1="18" y1="75" x2="302" y2="75" />
              <line className="curve-threshold-line curve-threshold-line--recall" x1="18" y1="75.2" x2="302" y2="75.2" />
              <line className="curve-threshold-line curve-threshold-line--forget" x1="18" y1="88.7" x2="302" y2="88.7" />
              <polyline className="curve-trend-fill" points={`18,122 ${decayPolyline} 302,122`} />
              <polyline className="curve-trend-line" points={decayPolyline} />
              {decayPoints.map((point, index) => {
                const x = 18 + index * 71;
                const y = 18 + (1 - point.score) * 104;
                return (
                  <g key={point.day}>
                    <circle className="curve-point" cx={x} cy={y} r="4.5" />
                    <text className="curve-point-label" x={x} y={y - 10}>{point.score.toFixed(2)}</text>
                    <text className="curve-day-label" x={x} y="142">{point.day}</text>
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="curve-thresholds">
            <span>Recall threshold <strong>0.45</strong></span>
            <span>Forget threshold <strong>0.32</strong></span>
            <span>Next sweep <strong>2026-04-28 09:00</strong></span>
          </div>
        </section>
        <section className="curve-panel">
          <h3>Review queue</h3>
          {fadingMemories.map((memory) => (
            <ForgettingMemoryRow key={memory.id} memory={memory} decision={decisions[memory.id]} onDecision={onDecision} />
          ))}
          {forgettingItems.map((item) => (
            <button key={item.title} className="curve-review-row curve-review-row--task" type="button" onClick={() => onSelect(item)}>
              <Clock3 size={17} />
              <span>{item.title}</span>
              <StrengthMeter value={0.48} compact />
              <StatusPill label={decisions[`${item.type}:${item.title}:${item.updated}`] ?? maintenanceStateLabel(dictionary, item.state)} tone="orange" />
            </button>
          ))}
        </section>
      </div>
    </>
  );
}

function ForgettingMemoryRow({
  memory,
  decision,
  onDecision,
}: {
  memory: MemoryItem;
  decision?: string;
  onDecision: (key: string, decision: string) => void;
}) {
  const { dictionary } = useI18n();
  return (
    <section className="curve-review-row curve-review-row--memory">
      <FileText size={17} />
      <span>{memory.title}</span>
      <StrengthMeter value={memory.forgetting.decayScore} compact />
      <StatusPill label={decision ?? curveStateLabel(dictionary, memory.forgetting.curveState)} tone={memory.forgetting.curveState === "ready_to_forget" ? "red" : "orange"} />
      <small>next review {memory.forgetting.nextReviewAt}</small>
      <div className="inline-action-row">
        <button type="button" onClick={() => onDecision(memory.id, "Reinforced")}>reinforce</button>
        <button type="button" onClick={() => onDecision(memory.id, "Keep")}>keep</button>
        <button type="button" onClick={() => onDecision(memory.id, "Forget queued")}>forget</button>
      </div>
    </section>
  );
}

function WorkerHealth({ compact, onAction }: { compact?: boolean; onAction?: (key: string, message: string) => void }) {
  const failedCount = workerHealthRows.filter((row) => row.status === "Failed").length;
  const warningCount = workerHealthRows.filter((row) => row.status === "Warning").length;

  return (
    <section className="worker-snapshot">
      <h2>{compact ? "Worker Health Snapshot" : "Worker Health"}</h2>
      {!compact ? (
        <div className="worker-health-summary">
          <span><strong>{workerHealthRows.length - failedCount}</strong> available workers</span>
          <span><strong>{warningCount}</strong> warning</span>
          <span><strong>{failedCount}</strong> failed</span>
        </div>
      ) : null}
      <div className={`compact-table ${compact ? "" : "compact-table--worker"}`}>
        {!compact ? (
          <div className="compact-row compact-row--with-actions compact-row--head">
            <span>Worker</span>
            <span>Status</span>
            <span>Last Run</span>
            <span>Failures</span>
            <span>Avg</span>
            <span>Queue</span>
            <span>Note</span>
            <span>Logs</span>
            <span>Restart</span>
          </div>
        ) : null}
        {workerHealthRows.map((row) => (
          <div key={row.worker} className={`compact-row ${compact ? "" : "compact-row--with-actions"}`}>
            <span>{row.worker}</span>
            <StatusPill label={row.status} tone={row.status === "Failed" ? "red" : row.status === "Warning" ? "orange" : "green"} />
            <span>{row.lastRun}</span>
            <span>{row.failures}</span>
            <span>{row.duration}</span>
            {!compact ? (
              <>
                <span>{row.queue}</span>
                <span>{row.note}</span>
                <button type="button" onClick={() => onAction?.(row.worker, `${row.worker} logs opened`)}>logs</button>
                <button type="button" onClick={() => onAction?.(row.worker, `${row.worker} restart requested`)} disabled={row.status === "Healthy"}>restart</button>
              </>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function JobHistory() {
  const [filter, setFilter] = useState("All");
  const filters = ["All", "Succeeded", "Failed", "Warning", "Skipped"];
  const visibleRows = filter === "All" ? jobHistoryRows : jobHistoryRows.filter((row) => row.status === filter);

  return (
    <div className="project-tab-panel">
      <div className="section-toolbar section-toolbar--flush">
        <h2>Job History</h2>
        <div className="chip-row">
          {filters.map((item) => <button key={item} className={item === filter ? "is-active" : ""} type="button" onClick={() => setFilter(item)}>{item}</button>)}
        </div>
      </div>
      <div className="audit-list">
        <section className="audit-row audit-row--head">
          <span>Time</span>
          <span>Status</span>
          <span>Job</span>
          <span>Worker</span>
          <span>Detail</span>
        </section>
        {visibleRows.map((row) => (
          <section key={`${row.time}-${row.title}`} className="audit-row">
            <span>{row.time}</span>
            <StatusPill label={row.status} tone={row.status === "Failed" ? "red" : row.status === "Succeeded" ? "green" : "orange"} />
            <strong>{row.title}</strong>
            <span>{row.worker}</span>
            <span>{row.detail}</span>
          </section>
        ))}
      </div>
    </div>
  );
}
