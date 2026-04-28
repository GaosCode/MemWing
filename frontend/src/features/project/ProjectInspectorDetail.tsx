import { ArrowLeft, Check, CircleAlert, Database, Eye, FileText, MoreHorizontal, RefreshCcw, Trash2, User } from "lucide-react";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, Metric, SimpleTable, StatusPill, Timeline } from "../../shared/components/ui";

export function ProjectInspectorDetail({ onBack }: { onBack: () => void }) {
  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Project</button>
          <h1>Project Inspector</h1>
          <p>Review project memory status, rebuild evidence, source coverage, and audit history.</p>
        </div>
        <div className="inline-action-row">
          <Button primary icon={Check} label="Confirm Changes" />
          <Button icon={Trash2} label="Discard" />
          <Button icon={Eye} label="View Source" />
          <IconButton label="More" icon={MoreHorizontal} />
        </div>
      </header>

      <div className="status-strip status-strip--detail">
        <Metric label="Strength" value="0.84" meter />
        <Metric label="Lifecycle" value="Active · Review Pending" tone="orange" />
        <Metric label="Last Rebuild" value="2026-04-27 11:32" />
        <Metric label="Version" value="v3 current" />
      </div>
      <DetailTabs tabs={["Overview", "Rebuild", "Sources", "Versions", "Audit", "Graph"]} />

      <div className="detail-layout">
        <article className="detail-document">
          <DocSection icon={FileText} title="Project Status Summary">
            <ul>
              <li>Project memory is active and pending review.</li>
              <li>Rebuild preview contains 3 candidate changes.</li>
              <li>Evidence coverage is sufficient, but two conflicts require attention.</li>
            </ul>
          </DocSection>
          <DocSection icon={RefreshCcw} title="Rebuild Candidate Changes">
            <SimpleTable columns={["Type", "Description", "Sources", "Confidence"]} rows={[
              ["Add", "Next Steps now include project memory drift checks.", "2 sources", "0.86"],
              ["Revise", "Current Stage updated to A3 Calm Operations consolidation.", "3 sources", "0.84"],
              ["Remove", "Older duplicate risk wording removed.", "1 source", "0.79"],
            ]} />
          </DocSection>
          <DocSection icon={Database} title="Source Coverage">
            <SimpleTable columns={["Source Group", "Evidence Count", "Last Seen", "Coverage"]} rows={[
              ["Feishu · 产品群", "14", "2026-04-27 11:32", "High"],
              ["Feishu · 安全群", "5", "2026-04-27 10:33", "Medium"],
              ["AI 产品自动化维护", "3", "2026-04-27 10:15", "Medium"],
              ["Others", "2", "2026-04-26 18:44", "Low"],
            ]} />
          </DocSection>
          <DocSection icon={CircleAlert} title="Open Risks">
            <ul className="two-column-list">
              <li>Overwriting stable project context during rebuild.<StatusPill label="High" tone="red" /></li>
              <li>Insufficient evidence for promoted decisions.<StatusPill label="Medium" tone="orange" /></li>
              <li>Stale unresolved questions staying active too long.<StatusPill label="Low" tone="green" /></li>
            </ul>
          </DocSection>
        </article>

        <aside className="detail-side">
          <InspectorSection title="Version History">
            <Timeline rows={["v3 current · 2026-04-27 11:32", "v2 · 2026-04-27 11:05", "v1 · 2026-04-27 10:15"]} compact />
          </InspectorSection>
          <InspectorSection title="Audit Summary">
            <Definition label="Evidence Linked">24</Definition>
            <Definition label="Memories Linked">7</Definition>
            <Definition label="Conflicts Detected">2</Definition>
            <Definition label="Redactions Applied">1</Definition>
            <Definition label="Stale Items">0</Definition>
          </InspectorSection>
          <InspectorSection title="Recent Audit Events">
            <Timeline rows={["11:32 Rebuild preview generated", "11:05 Project stage revised", "10:33 Conflict scan completed", "10:15 Initial project memory captured"]} compact />
          </InspectorSection>
          <InspectorSection title="Captured by">
            <div className="capture-user"><span className="avatar"><User size={16} /></span><strong>swift.gao</strong></div>
            <p>Last Updated: 2026-04-27 11:32:18</p>
          </InspectorSection>
        </aside>
      </div>
    </section>
  );
}
