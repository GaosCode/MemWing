import { useState } from "react";
import { ArrowLeft, Check, CircleAlert, Database, Eye, FileText, GitBranch, MoreHorizontal, RefreshCcw, Trash2, User } from "lucide-react";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, Metric, SimpleTable, StatusPill, Timeline } from "../../shared/components/ui";

export function ProjectInspectorDetail({ onBack }: { onBack: () => void }) {
  const [activeTab, setActiveTab] = useState("Overview");
  const [reviewState, setReviewState] = useState("Review Pending");
  const [notice, setNotice] = useState("Project inspector is ready");
  const tabs = ["Overview", "Rebuild", "Sources", "Versions", "Audit", "Graph"];

  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Project</button>
          <h1>Project Inspector</h1>
          <p>Review project memory status, rebuild evidence, source coverage, and audit history.</p>
        </div>
        <div className="inline-action-row">
          <Button primary icon={Check} label="Confirm Changes" onClick={() => {
            setReviewState("Confirmed");
            setNotice("Project rebuild changes confirmed");
          }} />
          <Button icon={Trash2} label="Discard" onClick={() => {
            setReviewState("Discarded");
            setNotice("Project rebuild preview discarded");
          }} />
          <Button icon={Eye} label="View Source" onClick={() => setActiveTab("Sources")} />
          <IconButton label="More" icon={MoreHorizontal} onClick={() => setNotice("Project inspector command menu opened")} />
        </div>
      </header>

      <div className="status-strip status-strip--detail">
        <Metric label="Strength" value="0.84" meter />
        <Metric label="Lifecycle" value={`Active · ${reviewState}`} tone={reviewState === "Confirmed" ? "green" : "orange"} />
        <Metric label="Last Rebuild" value="2026-04-27 11:32" />
        <Metric label="Version" value="v3 current" />
      </div>
      <DetailTabs tabs={tabs} activeTab={activeTab} onSelect={setActiveTab} />
      <div className="notice-row"><Check size={15} />{notice}</div>

      <div className="detail-layout">
        <article className="detail-document">
          {activeTab === "Overview" ? <ProjectInspectorOverview /> : null}
          {activeTab === "Rebuild" ? <ProjectInspectorRebuild state={reviewState} /> : null}
          {activeTab === "Sources" ? <ProjectInspectorSources /> : null}
          {activeTab === "Versions" ? <ProjectInspectorVersions /> : null}
          {activeTab === "Audit" ? <ProjectInspectorAudit /> : null}
          {activeTab === "Graph" ? <ProjectInspectorGraph /> : null}
        </article>

        <aside className="detail-side">
          <InspectorSection title="Version History" action="View all" onAction={() => setActiveTab("Versions")}>
            <Timeline rows={["v3 current · 2026-04-27 11:32", "v2 · 2026-04-27 11:05", "v1 · 2026-04-27 10:15"]} compact />
          </InspectorSection>
          <InspectorSection title="Audit Summary">
            <Definition label="Evidence Linked">24</Definition>
            <Definition label="Memories Linked">7</Definition>
            <Definition label="Conflicts Detected">2</Definition>
            <Definition label="Redactions Applied">1</Definition>
            <Definition label="Stale Items">0</Definition>
          </InspectorSection>
          <InspectorSection title="Recent Audit Events" action="View audit" onAction={() => setActiveTab("Audit")}>
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

function ProjectInspectorOverview() {
  return (
    <>
      <DocSection icon={FileText} title="Project Status Summary">
        <ul>
          <li>Project memory is active and pending review.</li>
          <li>Rebuild preview contains 3 candidate changes.</li>
          <li>Evidence coverage is sufficient, but two conflicts require attention.</li>
        </ul>
      </DocSection>
      <DocSection icon={CircleAlert} title="Open Risks">
        <ul className="two-column-list">
          <li>Overwriting stable project context during rebuild.<StatusPill label="High" tone="red" /></li>
          <li>Insufficient evidence for promoted decisions.<StatusPill label="Medium" tone="orange" /></li>
          <li>Stale unresolved questions staying active too long.<StatusPill label="Low" tone="green" /></li>
        </ul>
      </DocSection>
    </>
  );
}

function ProjectInspectorRebuild({ state }: { state: string }) {
  return (
    <DocSection icon={RefreshCcw} title="Rebuild Candidate Changes">
      <SimpleTable columns={["Type", "Description", "Sources", "Confidence"]} rows={[
        ["Add", "Next Steps now include project memory drift checks.", "2 sources", "0.86"],
        ["Revise", "Current Stage updated to A3 Calm Operations consolidation.", "3 sources", "0.84"],
        ["Remove", "Older duplicate risk wording removed.", "1 source", "0.79"],
        ["State", state, "local review", state === "Confirmed" ? "1.00" : "0.84"],
      ]} />
    </DocSection>
  );
}

function ProjectInspectorSources() {
  return (
    <DocSection icon={Database} title="Source Coverage">
      <SimpleTable columns={["Source Group", "Evidence Count", "Last Seen", "Coverage"]} rows={[
        ["Feishu · 产品群", "14", "2026-04-27 11:32", "High"],
        ["Feishu · 安全群", "5", "2026-04-27 10:33", "Medium"],
        ["AI 产品自动化维护", "3", "2026-04-27 10:15", "Medium"],
        ["Others", "2", "2026-04-26 18:44", "Low"],
      ]} />
    </DocSection>
  );
}

function ProjectInspectorVersions() {
  return (
    <DocSection icon={RefreshCcw} title="Version History">
      <Timeline rows={["v3 current · 2026-04-27 11:32", "v2 · 2026-04-27 11:05", "v1 · 2026-04-27 10:15"]} />
    </DocSection>
  );
}

function ProjectInspectorAudit() {
  return (
    <DocSection icon={CircleAlert} title="Audit Events">
      <Timeline rows={["11:32 Rebuild preview generated", "11:05 Project stage revised", "10:33 Conflict scan completed", "10:15 Initial project memory captured"]} />
    </DocSection>
  );
}

function ProjectInspectorGraph() {
  return (
    <DocSection icon={GitBranch} title="Project Memory Graph">
      <div className="memory-board memory-board--compact">
        {["Project Memory", "Source Events", "Linked Memories"].map((node) => (
          <section key={node} className="board-card">
            <strong>{node}</strong>
            <p>Connected to current project memory rebuild.</p>
          </section>
        ))}
      </div>
    </DocSection>
  );
}
