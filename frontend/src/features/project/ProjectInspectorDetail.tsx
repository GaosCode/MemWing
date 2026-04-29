import { useState } from "react";
import { ArrowLeft, Check, CircleAlert, Database, Eye, FileText, GitBranch, GitCompare, MoreHorizontal, Network, RefreshCcw, ShieldCheck, Trash2, User } from "lucide-react";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, Metric, SimpleTable, StatusPill, Timeline } from "../../shared/components/ui";
import { auditEvents, projectSources, projectVersions, rebuildChanges } from "./projectData";
import { ProjectRebuildChangeList } from "./ProjectRebuildChangeList";

export function ProjectInspectorDetail({ onBack }: { onBack: () => void }) {
  const [activeTab, setActiveTab] = useState("Overview");
  const [reviewState, setReviewState] = useState("Review Pending");
  const [notice, setNotice] = useState("Project inspector is ready");
  const [selectedSource, setSelectedSource] = useState<string>(projectSources[0].name);
  const [selectedVersion, setSelectedVersion] = useState<string>(projectVersions[0].version);
  const [auditFilter, setAuditFilter] = useState("All");
  const tabs = ["Overview", "Rebuild", "Sources", "Versions", "Audit", "Graph"];

  function confirmChanges() {
    setReviewState("Confirmed");
    setNotice("Project rebuild changes confirmed");
  }

  function discardChanges() {
    setReviewState("Discarded");
    setNotice("Project rebuild preview discarded");
  }

  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Project</button>
          <h1>Project Inspector</h1>
          <p>Review project memory status, rebuild evidence, source coverage, and audit history.</p>
        </div>
        <div className="inline-action-row">
          <Button primary icon={Check} label="Confirm Changes" onClick={confirmChanges} />
          <Button icon={Trash2} label="Discard" onClick={discardChanges} />
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
          {activeTab === "Rebuild" ? <ProjectInspectorRebuild state={reviewState} onConfirm={confirmChanges} onDiscard={discardChanges} onSources={() => setActiveTab("Sources")} /> : null}
          {activeTab === "Sources" ? <ProjectInspectorSources selectedSource={selectedSource} onSelect={setSelectedSource} onNotice={setNotice} /> : null}
          {activeTab === "Versions" ? <ProjectInspectorVersions selectedVersion={selectedVersion} onSelect={setSelectedVersion} onNotice={setNotice} /> : null}
          {activeTab === "Audit" ? <ProjectInspectorAudit activeFilter={auditFilter} onFilter={setAuditFilter} /> : null}
          {activeTab === "Graph" ? <ProjectInspectorGraph onSources={() => setActiveTab("Sources")} /> : null}
        </article>

        <aside className="detail-side">
          <InspectorSection title="Version History" action="View all" onAction={() => setActiveTab("Versions")}>
            <Timeline rows={projectVersions.map((version) => `${version.version} ${version.label} · ${version.time}`)} compact />
          </InspectorSection>
          <InspectorSection title="Audit Summary">
            <Definition label="Evidence Linked">24</Definition>
            <Definition label="Memories Linked">7</Definition>
            <Definition label="Conflicts Detected">2</Definition>
            <Definition label="Redactions Applied">1</Definition>
            <Definition label="Stale Items">0</Definition>
          </InspectorSection>
          <InspectorSection title="Recent Audit Events" action="View audit" onAction={() => setActiveTab("Audit")}>
            <Timeline rows={auditEvents.slice(0, 4).map((event) => `${event.time} ${event.title}`)} compact />
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
      <DocSection icon={RefreshCcw} title="Rebuild Candidate Changes">
        <SimpleTable
          columns={["Type", "Description", "Sources", "Confidence"]}
          rows={rebuildChanges.map((change) => [change.type, change.summary, change.sources, change.confidence])}
        />
      </DocSection>
      <DocSection icon={Database} title="Source Coverage">
        <SimpleTable
          columns={["Source Group", "Evidence Count", "Last Seen", "Coverage"]}
          rows={projectSources.map((source) => [source.name, String(source.events), source.lastSeen, source.coverage])}
        />
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

function ProjectInspectorRebuild({
  state,
  onConfirm,
  onDiscard,
  onSources,
}: {
  state: string;
  onConfirm: () => void;
  onDiscard: () => void;
  onSources: () => void;
}) {
  return (
    <>
      <DocSection icon={RefreshCcw} title="Rebuild Candidate Changes">
        <ProjectRebuildChangeList onOpenSources={onSources} embedded />
      </DocSection>
      <DocSection icon={ShieldCheck} title="Review Gate">
        <p>Current state: <strong>{state}</strong>. Confirmation will create the next project memory version after backend persistence is available.</p>
        <div className="doc-section-actions">
          <Button primary icon={Check} label="Confirm Changes" onClick={onConfirm} />
          <Button icon={Trash2} label="Discard Preview" onClick={onDiscard} />
        </div>
      </DocSection>
    </>
  );
}

function ProjectInspectorSources({
  selectedSource,
  onSelect,
  onNotice,
}: {
  selectedSource: string;
  onSelect: (source: string) => void;
  onNotice: (notice: string) => void;
}) {
  const source = projectSources.find((item) => item.name === selectedSource) ?? projectSources[0];

  return (
    <DocSection icon={Database} title="Source Coverage">
      <div className="project-split-panel project-split-panel--embedded">
        <div className="source-list">
          {projectSources.map((item) => (
            <button key={item.name} className={item.name === selectedSource ? "is-selected" : ""} type="button" onClick={() => onSelect(item.name)}>
              <span>{item.name}</span>
              <strong>{item.events} events</strong>
              <StatusPill label={item.coverage} tone={item.coverage === "High" ? "green" : item.coverage === "Medium" ? "orange" : "red"} />
            </button>
          ))}
        </div>
        <article className="source-detail">
          <h3>{source.name}</h3>
          <p>{source.use}</p>
          <SimpleTable columns={["Field", "Value", "State", "Action"]} rows={[
            ["Evidence Count", String(source.events), source.status, "open"],
            ["Last Seen", source.lastSeen, source.coverage, "review"],
          ]} />
          <div className="inline-action-row">
            <Button icon={Eye} label="Open Evidence" onClick={() => onNotice(`${source.name} evidence opened`)} />
            <Button icon={ShieldCheck} label="Mark Reviewed" onClick={() => onNotice(`${source.name} marked reviewed`)} />
          </div>
        </article>
      </div>
    </DocSection>
  );
}

function ProjectInspectorVersions({
  selectedVersion,
  onSelect,
  onNotice,
}: {
  selectedVersion: string;
  onSelect: (version: string) => void;
  onNotice: (notice: string) => void;
}) {
  const version = projectVersions.find((item) => item.version === selectedVersion) ?? projectVersions[0];

  return (
    <DocSection icon={RefreshCcw} title="Version History">
      <div className="project-split-panel project-split-panel--embedded">
        <div className="source-list">
          {projectVersions.map((item) => (
            <button key={item.version} className={item.version === selectedVersion ? "is-selected" : ""} type="button" onClick={() => onSelect(item.version)}>
              <span>{item.version} · {item.label}</span>
              <strong>{item.time}</strong>
              <StatusPill label={item.state} tone={item.state === "Current" ? "green" : "gray"} />
            </button>
          ))}
        </div>
        <article className="source-detail">
          <h3>{version.summary}</h3>
          <p>Captured by {version.author} at {version.time}.</p>
          <div className="version-diff">
            <div><span>Add</span><p>Project memory drift checks.</p></div>
            <div><span>Revise</span><p>A3 Calm Operations wording.</p></div>
            <div><span>Remove</span><p>Duplicate risk wording.</p></div>
          </div>
          <div className="inline-action-row">
            <Button icon={GitCompare} label="Compare" onClick={() => onNotice(`${version.version} comparison opened`)} />
            <Button icon={RefreshCcw} label="Restore Preview" onClick={() => onNotice(`${version.version} restore preview opened`)} disabled={version.state === "Current"} />
          </div>
        </article>
      </div>
    </DocSection>
  );
}

function ProjectInspectorAudit({
  activeFilter,
  onFilter,
}: {
  activeFilter: string;
  onFilter: (filter: string) => void;
}) {
  const filters = ["All", "Rebuild", "Evidence", "Version", "Conflict"];
  const rows = activeFilter === "All" ? auditEvents : auditEvents.filter((event) => event.type === activeFilter);

  return (
    <DocSection icon={CircleAlert} title="Audit Events">
      <div className="chip-row chip-row--section">
        {filters.map((filter) => <button key={filter} className={filter === activeFilter ? "is-active" : ""} type="button" onClick={() => onFilter(filter)}>{filter}</button>)}
      </div>
      <div className="audit-list audit-list--embedded">
        {rows.map((event) => (
          <section key={`${event.time}-${event.title}`} className="audit-row">
            <span>{event.time}</span>
            <StatusPill label={event.type} tone={event.type === "Conflict" ? "red" : event.type === "Rebuild" ? "green" : "orange"} />
            <strong>{event.title}</strong>
            <span>{event.actor}</span>
          </section>
        ))}
      </div>
    </DocSection>
  );
}

function ProjectInspectorGraph({ onSources }: { onSources: () => void }) {
  return (
    <DocSection icon={GitBranch} title="Project Memory Graph">
      <div className="project-graph project-graph--embedded">
        {["Project Memory", "Source Events", "Linked Memories", "Audit Trail"].map((node, index) => (
          <button key={node} type="button" className={`graph-node graph-node--${index}`} onClick={index === 1 ? onSources : undefined}>
            <Network size={18} />
            <strong>{node}</strong>
            <span>{index === 0 ? "v3 current" : `${index + 3} links`}</span>
          </button>
        ))}
      </div>
    </DocSection>
  );
}
