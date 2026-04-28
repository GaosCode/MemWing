import { ArrowLeft, CircleAlert, Database, Eye, ExternalLink, FileText, Link2, MoreHorizontal, RotateCcw, ShieldCheck, Wrench } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, Metric, StatusBadge, StatusPill, Timeline } from "../../shared/components/ui";
import { memoryTypeLabel } from "../../shared/design-system/status";

export function MaintenanceDetailPage({ onBack }: { onBack: () => void }) {
  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Maintenance</button>
          <h1>PushWorker failed to promote candidate into Project Memory</h1>
          <p>Failed Job · PushWorker · Project Memory · 2026-04-27 11:15</p>
        </div>
        <div className="inline-action-row">
          <Button icon={RotateCcw} label="Retry Job" />
          <Button icon={ShieldCheck} label="Open Audit" />
          <Button icon={Eye} label="View Source" />
          <IconButton label="More" icon={MoreHorizontal} />
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
      <DetailTabs tabs={["Overview", "Failure Trace", "Linked Evidence", "Affected Memories", "Audit", "Retries", "Logs"]} />

      <div className="maintenance-detail-grid">
        <article className="detail-document">
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
        </article>

        <article className="detail-document detail-document--middle">
          <DocSection icon={Link2} title="Linked References">
            <div className="reference-grid reference-grid--wide">
              {["source_events · 5 events", "memory_items · 3 items", "memory_pages · 1 page", "audit_events · 2 events"].map((ref) => (
                <button key={ref}><FileText size={18} />{ref}<ExternalLink size={16} /></button>
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
