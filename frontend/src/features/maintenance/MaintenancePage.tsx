import { MoreHorizontal, Pause, RotateCcw } from "lucide-react";
import { maintenanceItems } from "../../shared/api/mockData";
import { Button, IconButton, Metric, PageHeader, ScrollableTabs, StatusPill } from "../../shared/components/ui";
import { severityStatus } from "../../shared/design-system/status";
import type { MaintenanceItem } from "../../shared/types/entities";

export function MaintenancePage({
  selected,
  onSelect,
}: {
  selected: MaintenanceItem;
  onSelect: (item: MaintenanceItem) => void;
}) {
  return (
    <>
      <PageHeader
        title="Maintenance"
        subtitle="Monitor memory automation, review maintenance tasks, and recover failed jobs safely."
        actions={
          <>
            <Button icon={Pause} label="Pause Queue" />
            <Button icon={RotateCcw} label="Retry Failed" />
            <IconButton label="More" icon={MoreHorizontal} />
          </>
        }
      />

      <div className="status-strip">
        <Metric label="Queue" value="Running" tone="green" />
        <Metric label="Needs Review" value="7" tone="orange" />
        <Metric label="Failed Jobs" value="2" tone="red" />
        <Metric label="Workers Healthy" value="4 / 5" tone="green" />
        <Metric label="Last Run" value="2026-04-27 11:32" />
      </div>

      <ScrollableTabs
        label="Maintenance tabs"
        activeTab="Needs Attention"
        tabs={["Overview", "Needs Attention", "Review Queue", "Recent Failures", "Push Candidates", "Forgetting Review", "Worker Health", "Job History"]}
      />

      <div className="section-toolbar">
        <h2>Needs Attention</h2>
        <div className="chip-row">
          {["All", "Failed", "Review", "Push", "Forgetting"].map((chip, index) => (
            <button key={chip} className={index === 0 ? "is-active" : ""}>{chip}</button>
          ))}
        </div>
      </div>

      <div className="maintenance-table">
        <div className="maintenance-row maintenance-row--head">
          <span>Type</span>
          <span>Item</span>
          <span>Source</span>
          <span>Reason</span>
          <span>State</span>
          <span>Updated</span>
        </div>
        {maintenanceItems.map((item) => (
          <button
            key={`${item.title}-${item.updated}`}
            className={`maintenance-row ${selected.title === item.title ? "is-selected" : ""}`}
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

      <section className="worker-snapshot">
        <h2>Worker Health Snapshot</h2>
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
    </>
  );
}
