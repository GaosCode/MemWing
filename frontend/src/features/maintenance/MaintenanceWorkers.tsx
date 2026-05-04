import { useMemo, useState } from "react";
import { StatusPill } from "../../shared/components/ui";
import type { MaintenanceItem } from "../../shared/types/entities";
import { jobHistoryRows, workerHealthRows } from "./maintenanceData";

export function WorkerHealth({
  compact,
  items,
  onInspect,
  onRestart,
}: {
  compact?: boolean;
  items: MaintenanceItem[];
  onInspect?: (item: MaintenanceItem) => void;
  onRestart?: (item: MaintenanceItem) => void;
}) {
  const backendJobs = items.filter((item) => item.actionKind === "job");
  const failedCount = backendJobs.filter((item) => item.state === "Failed").length;
  const warningCount = backendJobs.filter((item) => item.state === "Review Pending").length;
  const rows = backendJobs.length > 0 ? backendJobs : workerHealthRows.map((row) => ({
    id: row.worker,
    actionKind: "job",
    jobKind: row.worker,
    type: "Job",
    title: row.worker,
    state: row.status === "Failed" ? "Failed" : row.status === "Warning" ? "Review Pending" : "Open",
    updated: row.lastRun,
    reason: row.note,
    source: row.queue,
    retryable: row.status !== "Healthy",
    severity: row.status === "Failed" ? "failed" : row.status === "Warning" ? "warning" : "healthy",
  } as MaintenanceItem));

  return (
    <section className="worker-snapshot">
      <h2>{compact ? "Worker Health Snapshot" : "Worker Health"}</h2>
      {!compact ? (
        <div className="worker-health-summary">
          <span><strong>{Math.max(rows.length - failedCount, 0)}</strong> available jobs</span>
          <span><strong>{warningCount}</strong> warning</span>
          <span><strong>{failedCount}</strong> failed</span>
        </div>
      ) : null}
      <div className={`compact-table ${compact ? "" : "compact-table--worker"}`}>
        {!compact ? (
          <div className="compact-row compact-row--with-actions compact-row--head">
            <span>Worker</span>
            <span>Status</span>
            <span>Next Run</span>
            <span>Reason</span>
            <span>Source</span>
            <span>Logs</span>
            <span>Restart</span>
          </div>
        ) : null}
        {rows.map((row) => (
          <div key={row.id} className={`compact-row ${compact ? "" : "compact-row--with-actions"}`}>
            <span>{row.title}</span>
            <StatusPill label={row.state} tone={row.state === "Failed" ? "red" : row.state === "Review Pending" ? "orange" : "green"} />
            <span>{row.updated}</span>
            <span>{row.reason}</span>
            {!compact ? (
              <>
                <span>{row.source}</span>
                <button type="button" onClick={() => onInspect?.(row)} disabled={!onInspect}>logs</button>
                <button type="button" onClick={() => onRestart?.(row)} disabled={!row.retryable || !onRestart}>restart</button>
              </>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

export function JobHistory({ items }: { items: MaintenanceItem[] }) {
  const [filter, setFilter] = useState("All");
  const backendRows = useMemo(
    () => items.filter((item) => item.actionKind === "job").map((item) => ({
      time: item.updated,
      status: item.state === "Failed" ? "Failed" : "Succeeded",
      title: item.title,
      worker: item.source,
      detail: item.reason,
    })),
    [items],
  );
  const rows = backendRows.length > 0 ? backendRows : jobHistoryRows;
  const filters = ["All", "Succeeded", "Failed", "Warning", "Skipped"];
  const visibleRows = filter === "All" ? rows : rows.filter((row) => row.status === filter);

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
