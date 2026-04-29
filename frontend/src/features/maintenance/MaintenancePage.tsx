import { useState } from "react";
import { Check, Clock3, MoreHorizontal, Pause, Play, RotateCcw, TrendingDown } from "lucide-react";
import { maintenanceItems } from "../../shared/api/mockData";
import { Button, IconButton, Metric, PageHeader, ScrollableTabs, StatusPill, StrengthMeter } from "../../shared/components/ui";
import { severityStatus } from "../../shared/design-system/status";
import type { MaintenanceItem } from "../../shared/types/entities";

const maintenanceTabs = ["Overview", "Needs Attention", "Review Queue", "Recent Failures", "Push Candidates", "Forgetting Review", "Worker Health", "Job History"];
const chips = ["All", "Failed", "Review", "Push", "Forgetting"];

export function MaintenancePage({
  selected,
  onSelect,
}: {
  selected: MaintenanceItem;
  onSelect: (item: MaintenanceItem) => void;
}) {
  const [activeTab, setActiveTab] = useState("Needs Attention");
  const [activeChip, setActiveChip] = useState("All");
  const [queuePaused, setQueuePaused] = useState(false);
  const [notice, setNotice] = useState("Automation queue is live");

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
        title="Maintenance"
        subtitle="Monitor memory automation, review maintenance tasks, and recover failed jobs safely."
        actions={
          <>
            <Button icon={queuePaused ? Play : Pause} label={queuePaused ? "Resume Queue" : "Pause Queue"} onClick={() => {
              setQueuePaused((value) => !value);
              setNotice(queuePaused ? "Queue resumed" : "Queue paused for manual review");
            }} />
            <Button icon={RotateCcw} label="Retry Failed" onClick={() => setNotice("Retry scheduled for 2 failed jobs")} />
            <IconButton label="More" icon={MoreHorizontal} onClick={() => setNotice("Maintenance command menu opened")} />
          </>
        }
      />

      <div className="status-strip">
        <Metric label="Queue" value={queuePaused ? "Paused" : "Running"} tone={queuePaused ? "orange" : "green"} />
        <Metric label="Needs Review" value="7" tone="orange" />
        <Metric label="Failed Jobs" value="2" tone="red" />
        <Metric label="Workers Healthy" value="4 / 5" tone="green" />
        <Metric label="Last Run" value="2026-04-27 11:32" />
      </div>

      <ScrollableTabs
        label="Maintenance tabs"
        activeTab={activeTab}
        tabs={maintenanceTabs}
        onSelect={setActiveTab}
      />

      <div className="notice-row"><Check size={15} />{notice}</div>

      {activeTab === "Overview" ? <MaintenanceOverview /> : null}
      {activeTab === "Needs Attention" ? (
        <NeedsAttention items={filteredItems} selected={selected} activeChip={activeChip} onSelect={onSelect} onChip={setActiveChip} />
      ) : null}
      {activeTab === "Review Queue" ? <QueueLane title="Review Queue" items={maintenanceItems.filter((item) => item.type === "Review")} onSelect={onSelect} /> : null}
      {activeTab === "Recent Failures" ? <QueueLane title="Recent Failures" items={maintenanceItems.filter((item) => item.state === "Failed")} onSelect={onSelect} /> : null}
      {activeTab === "Push Candidates" ? <QueueLane title="Push Candidates" items={maintenanceItems.filter((item) => item.type === "Push")} onSelect={onSelect} /> : null}
      {activeTab === "Forgetting Review" ? <ForgettingReview onSelect={onSelect} onRefresh={() => setNotice("Decay scores refreshed for forgetting review")} /> : null}
      {activeTab === "Worker Health" ? <WorkerHealth /> : null}
      {activeTab === "Job History" ? <JobHistory /> : null}
    </>
  );
}

function MaintenanceOverview() {
  return (
    <div className="overview-grid">
      {[
        ["Needs Attention", "7", "Review conflict, stale wording, and forgetting candidates."],
        ["Forgetting Review", "2", "Memories are below review threshold and need retention decisions."],
        ["Push Candidates", "4", "Validated memories waiting for project memory push."],
        ["Worker Health", "4 / 5", "PushWorker is failed; other workers are healthy."],
      ].map(([title, value, body]) => (
        <section key={title} className="overview-panel">
          <span>{title}</span>
          <strong>{value}</strong>
          <p>{body}</p>
        </section>
      ))}
    </div>
  );
}

function NeedsAttention({
  items,
  selected,
  activeChip,
  onSelect,
  onChip,
}: {
  items: MaintenanceItem[];
  selected: MaintenanceItem;
  activeChip: string;
  onSelect: (item: MaintenanceItem) => void;
  onChip: (chip: string) => void;
}) {
  return (
    <>
      <div className="section-toolbar">
        <h2>Needs Attention</h2>
        <div className="chip-row">
          {chips.map((chip) => (
            <button key={chip} className={activeChip === chip ? "is-active" : ""} type="button" onClick={() => onChip(chip)}>{chip}</button>
          ))}
        </div>
      </div>
      <MaintenanceTable items={items} selected={selected} onSelect={onSelect} />
      <WorkerHealth compact />
    </>
  );
}

function QueueLane({
  title,
  items,
  onSelect,
}: {
  title: string;
  items: MaintenanceItem[];
  onSelect: (item: MaintenanceItem) => void;
}) {
  return (
    <>
      <div className="section-toolbar">
        <h2>{title}</h2>
        <span className="muted-count">{items.length} items</span>
      </div>
      <MaintenanceTable items={items} onSelect={onSelect} />
    </>
  );
}

function MaintenanceTable({
  items,
  selected,
  onSelect,
}: {
  items: MaintenanceItem[];
  selected?: MaintenanceItem;
  onSelect: (item: MaintenanceItem) => void;
}) {
  return (
    <div className="maintenance-table">
      <div className="maintenance-row maintenance-row--head">
        <span>Type</span>
        <span>Item</span>
        <span>Source</span>
        <span>Reason</span>
        <span>State</span>
        <span>Updated</span>
      </div>
      {items.map((item) => (
        <button
          key={`${item.title}-${item.updated}`}
          className={`maintenance-row ${selected?.title === item.title ? "is-selected" : ""}`}
          onClick={() => onSelect(item)}
        >
          <StatusPill label={item.type} tone={severityStatus[item.severity].tone} />
          <span>{item.title}</span>
          <span>{item.source}</span>
          <span>{item.reason}</span>
          <span><StatusPill label={item.state} tone={item.state === "Failed" ? "red" : item.state === "Open" ? "green" : "orange"} /></span>
          <span>{item.updated}</span>
        </button>
      ))}
    </div>
  );
}

function ForgettingReview({ onSelect, onRefresh }: { onSelect: (item: MaintenanceItem) => void; onRefresh: () => void }) {
  const forgettingItems = maintenanceItems.filter((item) => item.type === "Forgetting" || item.state === "Ready to forget");
  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Forgetting Curve Review</h2>
          <p className="section-subtitle">Review decay score, next review, and retention reason before memory is forgotten.</p>
        </div>
        <Button icon={TrendingDown} label="Refresh Decay Scores" onClick={onRefresh} />
      </div>
      <div className="curve-review-grid">
        <section className="curve-panel">
          <h3>Decay thresholds</h3>
          <div className="curve-line" aria-hidden="true">
            {[0.92, 0.78, 0.61, 0.48, 0.31].map((score, index) => <span key={score} style={{ height: `${score * 100}%`, left: `${index * 24}%` }} />)}
          </div>
          <p>Recall threshold: 0.45 · Forget threshold: 0.32 · next sweep: 2026-04-28 09:00</p>
        </section>
        <section className="curve-panel">
          <h3>Review queue</h3>
          {forgettingItems.map((item) => (
            <button key={item.title} className="curve-review-row" type="button" onClick={() => onSelect(item)}>
              <Clock3 size={17} />
              <span>{item.title}</span>
              <StrengthMeter value={0.48} compact />
              <StatusPill label={item.state} tone="orange" />
            </button>
          ))}
        </section>
      </div>
    </>
  );
}

function WorkerHealth({ compact }: { compact?: boolean }) {
  return (
    <section className="worker-snapshot">
      <h2>{compact ? "Worker Health Snapshot" : "Worker Health"}</h2>
      <div className="compact-table">
        {[
          ["LongTermFilter", "Healthy", "11:32", "0", "1.2s"],
          ["GraphWriteWorker", "Warning", "11:30", "1", "2.8s"],
          ["PageMemoryWorker", "Healthy", "11:28", "0", "3.1s"],
          ["DecayWorker", "Healthy", "11:20", "0", "1.7s"],
          ["PushWorker", "Failed", "11:15", "2", "4.6s"],
        ].map(([worker, status, run, failures, duration]) => (
          <div key={worker} className="compact-row">
            <span>{worker}</span>
            <StatusPill label={status} tone={status === "Failed" ? "red" : status === "Warning" ? "orange" : "green"} />
            <span>{run}</span>
            <span>{failures}</span>
            <span>{duration}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function JobHistory() {
  return (
    <div className="timeline-board">
      {[
        ["11:32", "LongTermFilter refreshed memory strengths", "14 memories refreshed"],
        ["11:15", "PushWorker failed promotion", "Conflict threshold exceeded"],
        ["10:33", "DecayWorker completed forgetting review", "2 ready to forget"],
      ].map(([time, title, body]) => (
        <section key={time} className="timeline-card">
          <span>{time}</span>
          <strong>{title}</strong>
          <p>{body}</p>
        </section>
      ))}
    </div>
  );
}
