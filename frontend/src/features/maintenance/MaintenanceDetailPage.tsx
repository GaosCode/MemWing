import { useState } from "react";
import { ArrowLeft, Check, CircleAlert, Database, Eye, ExternalLink, FileText, Link2, MoreHorizontal, RotateCcw, ShieldCheck, Wrench } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, Metric, StatusBadge, StatusPill, Timeline } from "../../shared/components/ui";
import { memoryTypeLabel } from "../../shared/design-system/status";

export function MaintenanceDetailPage({ onBack }: { onBack: () => void }) {
  const [activeTab, setActiveTab] = useState("Overview");
  const [notice, setNotice] = useState("Promotion remains blocked until conflict review is complete");
  const tabs = ["Overview", "Failure Trace", "Linked Evidence", "Affected Memories", "Audit", "Retries", "Logs"];

  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Maintenance</button>
          <h1>PushWorker failed to promote candidate into Project Memory</h1>
          <p>Failed Job · PushWorker · Project Memory · 2026-04-27 11:15</p>
        </div>
        <div className="inline-action-row">
          <Button icon={RotateCcw} label="Retry Job" onClick={() => setNotice("Retry requested; waiting for conflict review")} />
          <Button icon={ShieldCheck} label="Open Audit" onClick={() => setActiveTab("Audit")} />
          <Button icon={Eye} label="View Source" onClick={() => setActiveTab("Linked Evidence")} />
          <IconButton label="More" icon={MoreHorizontal} onClick={() => setNotice("Job command menu opened")} />
        </div>
      </header>

      <div className="status-strip status-strip--detail">
        <Metric label="Status" value="Failed" tone="red" />
        <Metric label="Severity" value="High" tone="red" />
        <Metric label="Retry Count" value="2" />
        <Metric label="Affected Memories" value="3" />
        <Metric label="Worker" value="PushWorker" />
        <Metric label="Last Run" value="2026-04-27 11:15" />
      </div>
      <DetailTabs tabs={tabs} activeTab={activeTab} onSelect={setActiveTab} />
      <div className="notice-row"><Check size={15} />{notice}</div>

      <div className="maintenance-detail-grid">
        <article className="detail-document">
          {activeTab === "Overview" ? <MaintenanceOverviewDetail /> : null}
          {activeTab === "Failure Trace" ? <FailureTrace /> : null}
          {activeTab === "Linked Evidence" ? <LinkedEvidence /> : null}
          {activeTab === "Affected Memories" ? <AffectedMemories /> : null}
          {activeTab === "Audit" ? <AuditTrace /> : null}
          {activeTab === "Retries" ? <RetryTrace /> : null}
          {activeTab === "Logs" ? <LogTrace /> : null}
        </article>

        <article className="detail-document detail-document--middle">
          <DocSection icon={Link2} title="Linked References">
            <div className="reference-grid reference-grid--wide">
              {["source_events · 5 events", "memory_items · 3 items", "memory_pages · 1 page", "audit_events · 2 events"].map((ref) => (
                <button key={ref} type="button" onClick={() => setNotice(`${ref} opened in linked evidence preview`)}><FileText size={18} />{ref}<ExternalLink size={16} /></button>
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
            <Definition label="Worker">PushWorker</Definition>
            <Definition label="Queue">maintenance.push</Definition>
            <Definition label="Duration">4.6s</Definition>
          </InspectorSection>
          <InspectorSection title="Retry History">
            <Timeline rows={["11:15 Failed · conflict threshold exceeded", "11:05 Skipped · pending review", "10:33 Warning · stale candidate state"]} compact />
          </InspectorSection>
          <InspectorSection title="Worker Health">
            <Definition label="Current status"><StatusPill label="Failed" tone="red" /></Definition>
            <Definition label="Avg duration">4.6s</Definition>
            <Definition label="Failures in 24h">2</Definition>
            <Definition label="Last healthy run">2026-04-27 10:33</Definition>
          </InspectorSection>
        </aside>
      </div>
    </section>
  );
}

function MaintenanceOverviewDetail() {
  return (
    <>
      <DocSection icon={CircleAlert} title="Failure Summary">
        <p>PushWorker attempted to promote a maintenance candidate into Project Memory, but the candidate touched an active project section with unresolved contradictions. Promotion was stopped before writing to the project memory.</p>
      </DocSection>
      <DocSection icon={CircleAlert} title="Reason">
        <p>Conflict threshold exceeded during promotion. The candidate overlaps with an active Project Memory section and requires manual review before retry.</p>
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

function FailureTrace() {
  return (
    <>
      <DocSection icon={CircleAlert} title="Failure Trace">
        <Timeline rows={[
          "11:15:02 PushWorker started promotion",
          "11:15:04 Candidate matched Project Memory section",
          "11:15:07 Conflict threshold exceeded",
          "11:15:08 Promotion blocked before write",
        ]} />
      </DocSection>
      <DocSection icon={Wrench} title="Blocked Operation">
        <p>The candidate attempted to promote wording into an active project memory section before conflict state was resolved.</p>
      </DocSection>
    </>
  );
}

function LinkedEvidence() {
  return (
    <DocSection icon={Link2} title="Linked Evidence">
      <div className="timeline-board">
        {["source_events · Feishu planning thread", "memory_items · affected preferences", "audit_events · conflict scan"].map((row) => (
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
      <Timeline rows={["11:15 Promotion blocked", "11:15 Conflict audit linked", "11:14 Candidate selected", "11:12 Worker queue started"]} />
    </DocSection>
  );
}

function RetryTrace() {
  return (
    <DocSection icon={RotateCcw} title="Retry History">
      <Timeline rows={["11:15 Failed · conflict threshold exceeded", "11:05 Skipped · pending review", "10:33 Warning · stale candidate state"]} />
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
