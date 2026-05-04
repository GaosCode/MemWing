import { Eye, RotateCcw, ShieldCheck } from "lucide-react";
import { Button, StatusPill } from "../../shared/components/ui";
import type { StatusTone } from "../../shared/design-system/status";
import { severityTone } from "../../shared/design-system/status";
import { maintenanceStateLabel } from "../../shared/i18n/formatters";
import { useI18n } from "../../shared/i18n";
import type { LocaleDictionary } from "../../shared/i18n/locales/zh-CN";
import type { MaintenanceItem } from "../../shared/types/entities";

const chips = ["All", "Failed", "Review", "Push", "Forgetting"];

export type MaintenanceAction = "retry" | "approve" | "skip" | "send";

export function maintenanceItemKey(item: MaintenanceItem) {
  return `${item.actionKind}:${item.id}`;
}

export function chipLabel(dictionary: LocaleDictionary, chip: string) {
  const chipMap: Record<string, string> = {
    All: dictionary.maintenance.chips.all,
    Failed: dictionary.maintenance.chips.failed,
    Review: dictionary.maintenance.chips.review,
    Push: dictionary.maintenance.chips.push,
    Forgetting: dictionary.maintenance.chips.forgetting,
  };
  return chipMap[chip] ?? chip;
}

export function maintenanceStateTone(state: MaintenanceItem["state"]): StatusTone {
  if (state === "Failed") {
    return "red";
  }
  if (state === "Open" || state === "Sent") {
    return "green";
  }
  if (state === "Skipped") {
    return "gray";
  }
  return "orange";
}

export function filterMaintenanceItems(items: MaintenanceItem[], activeChip: string) {
  return items.filter((item) => {
    if (activeChip === "All") {
      return true;
    }
    if (activeChip === "Failed") {
      return item.state === "Failed";
    }
    return item.type === activeChip;
  });
}

export function NeedsAttention({
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
    </>
  );
}

export function ReviewQueue({
  items,
  actions,
  onSelect,
}: {
  items: MaintenanceItem[];
  actions: Record<string, string>;
  onSelect: (item: MaintenanceItem) => void;
}) {
  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Review Queue</h2>
          <p className="section-subtitle">Review tasks are projected from backend maintenance state.</p>
        </div>
        <span className="muted-count">{items.length} items</span>
      </div>
      <MaintenanceTable items={items} actions={actions} onSelect={onSelect} />
      <div className="action-list action-list--maintenance">
        {items.map((item) => (
          <section key={item.id} className="action-list-row action-list-row--review-queue">
            <StatusPill label={actions[maintenanceItemKey(item)] ?? item.state} tone="orange" />
            <span>{item.title}</span>
            <strong>{item.reason}</strong>
            <button type="button" onClick={() => onSelect(item)}>inspect</button>
          </section>
        ))}
        {items.length === 0 ? <p>No backend review task is currently open.</p> : null}
      </div>
    </>
  );
}

export function RecentFailures({
  items,
  actions,
  onSelect,
  onAction,
}: {
  items: MaintenanceItem[];
  actions: Record<string, string>;
  onSelect: (item: MaintenanceItem) => void;
  onAction: (item: MaintenanceItem, action: MaintenanceAction) => void;
}) {
  const { dictionary } = useI18n();
  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Recent Failures</h2>
          <p className="section-subtitle">Failed jobs can be retried through the Control Plane retry endpoint.</p>
        </div>
        <Button icon={RotateCcw} label="Retry Failed" onClick={() => items.forEach((item) => onAction(item, "retry"))} disabled={items.length === 0} />
      </div>
      <MaintenanceTable items={items} actions={actions} onSelect={onSelect} />
      <div className="failure-recovery">
        {items.map((item) => (
          <section key={item.id} className="failure-card">
            <StatusPill label={dictionary.status.queue.Blocked} tone="red" />
            <strong>{item.title}</strong>
            <p>{item.reason}. Retry is sent to the backend when the job is retryable.</p>
            <div className="inline-action-row">
              <Button primary icon={RotateCcw} label={dictionary.actions.retryJob} onClick={() => onAction(item, "retry")} disabled={!item.retryable} />
              <Button icon={ShieldCheck} label={dictionary.actions.openAudit} onClick={() => onSelect(item)} />
              <Button icon={Eye} label={dictionary.actions.viewSource} onClick={() => onSelect(item)} />
            </div>
          </section>
        ))}
        {items.length === 0 ? <p>No failed backend job is currently returned for this scope.</p> : null}
      </div>
    </>
  );
}

export function PushCandidates({
  items,
  actions,
  onSelect,
  onAction,
}: {
  items: MaintenanceItem[];
  actions: Record<string, string>;
  onSelect: (item: MaintenanceItem) => void;
  onAction: (item: MaintenanceItem, action: MaintenanceAction) => void;
}) {
  const { dictionary } = useI18n();

  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Push Candidates</h2>
          <p className="section-subtitle">Approvals and skips are persisted through backend push candidate endpoints.</p>
        </div>
        <span className="muted-count">{items.filter((item) => item.state === "Open").length} open</span>
      </div>
      <div className="push-candidate-summary">
        <section>
          <span>Ready to push</span>
          <strong>{items.filter((item) => item.state === "Open").length}</strong>
          <p>Open candidates can be approved or skipped.</p>
        </section>
        <section>
          <span>Approved</span>
          <strong>{items.filter((item) => item.state === "Approved").length}</strong>
          <p>Approved candidates can be sent as Feishu cards.</p>
        </section>
        <section>
          <span>Safety gate</span>
          <strong>Review required</strong>
          <p>Each action writes an audit event with the frontend actor id.</p>
        </section>
      </div>
      <div className="action-list action-list--maintenance">
        {items.map((item) => (
          <section key={item.id} className="action-list-row action-list-row--push-candidate">
            <StatusPill
              label={actions[maintenanceItemKey(item)] ?? maintenanceStateLabel(dictionary, item.state)}
              tone={maintenanceStateTone(item.state)}
            />
            <span>{item.title}</span>
            <strong>{item.reason}</strong>
            <span>{item.source}</span>
            <button type="button" onClick={() => onSelect(item)}>inspect</button>
            <button type="button" onClick={() => onAction(item, "approve")} disabled={item.state !== "Open"}>approve push</button>
            <button type="button" onClick={() => onAction(item, "send")} disabled={item.state !== "Approved"}>send card</button>
            <button type="button" onClick={() => onAction(item, "skip")} disabled={item.state !== "Open" && item.state !== "Approved"}>skip</button>
          </section>
        ))}
        {items.length === 0 ? <p>No push candidate is currently returned by the backend.</p> : null}
      </div>
    </>
  );
}

export function MaintenanceTable({
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
          key={item.id}
          className={`maintenance-row ${selected?.id === item.id ? "is-selected" : ""}`}
          onClick={() => onSelect(item)}
        >
          <StatusPill label={item.type} tone={severityTone[item.severity]} />
          <span>{item.title}</span>
          <span>{item.source}</span>
          <span>{item.reason}</span>
          <span><StatusPill label={actions?.[maintenanceItemKey(item)] ?? maintenanceStateLabel(dictionary, item.state)} tone={maintenanceStateTone(item.state)} /></span>
          <span>{item.updated}</span>
        </button>
      ))}
    </div>
  );
}
