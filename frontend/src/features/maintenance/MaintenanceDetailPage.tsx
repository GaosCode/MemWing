import { useState } from "react";
import { ArrowLeft, Check, CircleAlert, Database, Eye, ExternalLink, FileText, Link2, MoreHorizontal, RotateCcw, ShieldCheck, UserCheck, Wrench } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, Metric, StatusBadge, StatusPill, Timeline } from "../../shared/components/ui";
import { memoryTypeLabel, severityStatus } from "../../shared/design-system/status";
import type { MaintenanceItem } from "../../shared/types/entities";
import { auditTrailRows, linkedReferences, retryHistoryRows } from "./maintenanceData";

export function MaintenanceDetailPage({ item, onBack }: { item: MaintenanceItem; onBack: () => void }) {
  const [activeTab, setActiveTab] = useState("Overview");
  const [notice, setNotice] = useState("Promotion remains blocked until conflict review is complete");
  const [retryState, setRetryState] = useState(item.state);
  const tabs = ["Overview", "Failure Trace", "Linked Evidence", "Affected Memories", "Audit", "Retries", "Logs"];
  const severityMeta = severityStatus[item.severity];
  const isFailedJob = item.state === "Failed";

  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Maintenance</button>
          <h1>{item.title}</h1>
          <p>{item.type} · {item.source} · 2026-04-27 {item.updated}</p>
        </div>
        <div className="inline-action-row">
          <Button icon={RotateCcw} label={isFailedJob ? "Retry Job" : "Re-run Check"} onClick={() => {
            setRetryState(isFailedJob ? "Review Pending" : item.state);
            setNotice(isFailedJob ? "Retry requested; waiting for conflict review" : "Maintenance check queued");
          }} />
          <Button icon={ShieldCheck} label="Open Audit" onClick={() => setActiveTab("Audit")} />
          <Button icon={Eye} label="View Source" onClick={() => setActiveTab("Linked Evidence")} />
          <IconButton label="More" icon={MoreHorizontal} onClick={() => setNotice("Job command menu opened")} />
        </div>
      </header>

      <div className="status-strip status-strip--detail">
        <Metric label="Status" value={retryState} tone={retryState === "Failed" ? "red" : retryState === "Open" ? "green" : "orange"} />
        <Metric label="Severity" value={severityMeta.label} tone={severityMeta.tone === "gray" ? undefined : severityMeta.tone} />
        <Metric label="Retry Count" value={isFailedJob ? "2" : "0"} />
        <Metric label="Affected Memories" value={isFailedJob ? "3" : "1"} />
        <Metric label="Worker" value={isFailedJob ? "PushWorker" : item.type === "Forgetting" ? "DecayWorker" : "LongTermFilter"} />
        <Metric label="Last Run" value={`2026-04-27 ${item.updated}`} />
      </div>
      <DetailTabs tabs={tabs} activeTab={activeTab} onSelect={setActiveTab} />
      <div className="notice-row"><Check size={15} />{notice}</div>

      <div className="maintenance-detail-grid">
        <article className="detail-document">
          {activeTab === "Overview" ? <MaintenanceOverviewDetail item={item} isFailedJob={isFailedJob} /> : null}
          {activeTab === "Failure Trace" ? <FailureTrace item={item} /> : null}
          {activeTab === "Linked Evidence" ? <LinkedEvidence item={item} /> : null}
          {activeTab === "Affected Memories" ? <AffectedMemories /> : null}
          {activeTab === "Audit" ? <AuditTrace /> : null}
          {activeTab === "Retries" ? <RetryTrace /> : null}
          {activeTab === "Logs" ? <LogTrace /> : null}
        </article>

        <article className="detail-document detail-document--middle">
          <DocSection icon={Link2} title="Linked References">
            <div className="reference-grid reference-grid--wide">
              {linkedReferences.map((ref) => (
                <button key={ref.label} type="button" onClick={() => setNotice(`${ref.label} opened in linked evidence preview`)}><FileText size={18} />{ref.label}<span>{ref.count}</span><ExternalLink size={16} /></button>
              ))}
            </div>
          </DocSection>
          <DocSection icon={Database} title="Affected Memories">
            {memories.slice(0, 3).map((memory) => (
              <div className="affected-memory" key={memory.id}>
                <span>{memory.title}</span>
                <StatusPill label={memoryTypeLabel[memory.type]} tone="gray" />
                <StatusBadge status={memory.status} />
                <span>{memory.strength.toFixed(2)}</span>
              </div>
            ))}
          </DocSection>
          <DocSection icon={FileText} title="Recent Log Excerpt">
            <pre className="log-excerpt">{`11:15:02  PushWorker started promotion
11:15:04  Candidate matched Project Memory section
11:15:07  Conflict threshold exceeded
11:15:08  Promotion blocked before write
11:15:09  Manual review required`}</pre>
          </DocSection>
        </article>

        <aside className="detail-side">
          <InspectorSection title="Job Metadata">
            <Definition label="Job ID">job_push_20260427_1115</Definition>
            <Definition label="Worker">{isFailedJob ? "PushWorker" : item.type === "Forgetting" ? "DecayWorker" : "LongTermFilter"}</Definition>
            <Definition label="Queue">maintenance.push</Definition>
            <Definition label="Duration">4.6s</Definition>
          </InspectorSection>
          <InspectorSection title="Failure Classification">
            <Definition label="Type">{item.reason}</Definition>
            <Definition label="Severity">{severityMeta.label}</Definition>
            <Definition label="Write State">{isFailedJob ? "Blocked before write" : "No unsafe write"}</Definition>
            <Definition label="Recovery">{isFailedJob ? "Manual review then retry" : "Reviewer decision required"}</Definition>
          </InspectorSection>
          <InspectorSection title="Retry History">
            <Timeline rows={[...retryHistoryRows]} compact />
          </InspectorSection>
          <InspectorSection title="Audit Trail">
            <Timeline rows={[...auditTrailRows]} compact />
          </InspectorSection>
          <InspectorSection title="Worker Health">
            <Definition label="Current status"><StatusPill label={retryState} tone={retryState === "Failed" ? "red" : "orange"} /></Definition>
            <Definition label="Avg duration">4.6s</Definition>
            <Definition label="Failures in 24h">2</Definition>
            <Definition label="Last healthy run">2026-04-27 10:33</Definition>
            <div className="doc-section-actions">
              <Button icon={UserCheck} label="Acknowledge" onClick={() => setNotice("Worker health acknowledged")} />
            </div>
          </InspectorSection>
        </aside>
      </div>
    </section>
  );
}

function MaintenanceOverviewDetail({ item, isFailedJob }: { item: MaintenanceItem; isFailedJob: boolean }) {
  return (
    <>
      <DocSection icon={CircleAlert} title="Failure Summary">
        <p>{isFailedJob ? "PushWorker attempted to promote a maintenance candidate into Project Memory, but the candidate touched an active project section with unresolved contradictions. Promotion was stopped before writing to the project memory." : `${item.title} requires reviewer action before the automation queue can safely finish this maintenance step.`}</p>
      </DocSection>
      <DocSection icon={CircleAlert} title="Reason">
        <p>{item.reason}. {isFailedJob ? "The candidate overlaps with an active Project Memory section and requires manual review before retry." : "The item stays in maintenance until a reviewer confirms the lifecycle decision."}</p>
      </DocSection>
      <DocSection icon={Wrench} title="Recommended Recovery">
        <ol>
          <li>Review linked evidence.</li>
          <li>Open conflict audit and resolve contradiction state.</li>
          <li>Confirm affected memories are still current.</li>
          <li>Retry the job.</li>
        </ol>
      </DocSection>
      <DocSection icon={ShieldCheck} title="Safety Impact">
        <ul>
          <li>Project Memory was not overwritten.</li>
          <li>Candidate promotion was blocked.</li>
          <li>Existing memory versions remain unchanged.</li>
        </ul>
      </DocSection>
    </>
  );
}

function FailureTrace({ item }: { item: MaintenanceItem }) {
  const traceRows = item.state === "Failed"
    ? [
        "11:15:02 PushWorker started promotion",
        "11:15:04 Candidate matched Project Memory section",
        "11:15:07 Conflict threshold exceeded",
        "11:15:08 Promotion blocked before write",
      ]
    : [
        `${item.updated}:00 Maintenance item selected`,
        `${item.updated}:12 Evidence check queued`,
        `${item.updated}:24 Awaiting reviewer decision`,
      ];

  return (
    <>
      <DocSection icon={CircleAlert} title="Failure Trace">
        <Timeline rows={traceRows} />
      </DocSection>
      <DocSection icon={Wrench} title="Blocked Operation">
        <p>{item.state === "Failed" ? "The candidate attempted to promote wording into an active project memory section before conflict state was resolved." : "Automation is intentionally paused until the reviewer decision is recorded."}</p>
      </DocSection>
    </>
  );
}

function LinkedEvidence({ item }: { item: MaintenanceItem }) {
  return (
    <DocSection icon={Link2} title="Linked Evidence">
      <div className="timeline-board">
        {[`source_events · ${item.source}`, "memory_items · affected preferences", "audit_events · conflict scan"].map((row) => (
          <section className="timeline-card" key={row}>
            <span>Evidence</span>
            <strong>{row}</strong>
            <p>Review evidence before allowing another promotion attempt.</p>
          </section>
        ))}
      </div>
    </DocSection>
  );
}

function AffectedMemories() {
  return (
    <DocSection icon={Database} title="Affected Memories">
      {memories.slice(0, 3).map((memory) => (
        <div className="affected-memory" key={memory.id}>
          <span>{memory.title}</span>
          <StatusPill label={memoryTypeLabel[memory.type]} tone="gray" />
          <StatusBadge status={memory.status} />
          <span>{memory.strength.toFixed(2)}</span>
        </div>
      ))}
    </DocSection>
  );
}

function AuditTrace() {
  return (
    <DocSection icon={ShieldCheck} title="Audit Trail">
      <Timeline rows={[...auditTrailRows]} />
    </DocSection>
  );
}

function RetryTrace() {
  return (
    <DocSection icon={RotateCcw} title="Retry History">
      <Timeline rows={[...retryHistoryRows]} />
    </DocSection>
  );
}

function LogTrace() {
  return (
    <DocSection icon={FileText} title="Logs">
      <pre className="log-excerpt">{`11:15:02  PushWorker started promotion
11:15:04  Candidate matched Project Memory section
11:15:07  Conflict threshold exceeded
11:15:08  Promotion blocked before write
11:15:09  Manual review required`}</pre>
    </DocSection>
  );
}
