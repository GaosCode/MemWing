import { useState } from "react";
import {
  Check,
  CircleAlert,
  CircleCheck,
  Clock3,
  Database,
  Eye,
  FileText,
  GitBranch,
  GitCompare,
  History,
  Link2,
  List,
  MoreHorizontal,
  Network,
  RefreshCcw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { Button, DetailTabs, DocSection, IconButton, PageHeader, StatusPill } from "../../shared/components/ui";
import { auditEvents, projectSources, projectVersions, rebuildChanges } from "./projectData";
import { ProjectRebuildChangeList } from "./ProjectRebuildChangeList";

const projectTabs = ["Document", "Rebuild Preview", "Sources", "Versions", "Audit", "Graph"];

export function ProjectPage() {
  const [activeTab, setActiveTab] = useState("Document");
  const [previewState, setPreviewState] = useState<"pending" | "confirmed" | "discarded">("pending");
  const [linkedCount, setLinkedCount] = useState(3);
  const [editingSection, setEditingSection] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<string>(projectSources[0].name);
  const [selectedVersion, setSelectedVersion] = useState<string>(projectVersions[0].version);
  const [auditFilter, setAuditFilter] = useState("All");
  const [notice, setNotice] = useState("Rebuild preview is pending review");

  function confirmPreview() {
    setPreviewState("confirmed");
    setNotice("Rebuild changes confirmed; v4 preview is ready for version history");
    setActiveTab("Versions");
  }

  function discardPreview() {
    setPreviewState("discarded");
    setNotice("Rebuild changes discarded; current v3 remains unchanged");
  }

  function startRebuild() {
    setPreviewState("pending");
    setNotice("PageMemoryWorker queued a fresh rebuild preview");
    setActiveTab("Rebuild Preview");
  }

  return (
    <>
      <PageHeader
        title="Project Memory"
        subtitle="Maintain the project-level Page Memory with evidence-backed edits and rebuild previews."
        actions={
          <>
            <span className="header-meta">Last rebuilt: 2026-04-27 11:32</span>
            <StatusPill label={previewState === "confirmed" ? "v4 preview confirmed" : "v3 current"} tone={previewState === "confirmed" ? "green" : "orange"} />
            <Button icon={RefreshCcw} label="Run Rebuild" onClick={startRebuild} />
            <IconButton label="More" icon={MoreHorizontal} onClick={() => setNotice("Project command menu opened")} />
          </>
        }
      />

      {previewState === "pending" ? (
        <div className="rebuild-band">
          <div>
            <strong>Rebuild Preview</strong>
            <span className="outline-chip">3 changes</span>
            <p>Review candidate changes before confirming to the project memory. Current v3 remains untouched until confirmation.</p>
            <div className="inline-action-row">
              <Button primary icon={Check} label="Confirm" onClick={confirmPreview} />
              <Button icon={Trash2} label="Discard" onClick={discardPreview} />
            </div>
          </div>
          {rebuildChanges.map((change) => (
            <PreviewChange key={change.type} tone={change.tone} title={change.type} body={change.summary} sources={change.sources} />
          ))}
        </div>
      ) : (
        <div className="project-state-band">
          <span><ShieldCheck size={17} />Rebuild Preview</span>
          <strong>{previewState === "confirmed" ? "Changes confirmed locally" : "Candidate changes discarded"}</strong>
          <p>{previewState === "confirmed" ? "v4 preview is ready for version review; current v3 remains visible until backend persistence lands." : "No pending candidate is active. Run rebuild to generate a fresh preview."}</p>
          <Button icon={RefreshCcw} label="Run Rebuild" onClick={startRebuild} />
        </div>
      )}

      <DetailTabs tabs={projectTabs} activeTab={activeTab} onSelect={setActiveTab} />
      <div className="notice-row"><Check size={15} />{notice}</div>

      {activeTab === "Document" ? (
      <article className="document-workbench">
        <DocSection icon={FileText} index="1" title="Project Brief">
          <p>MemWing provides a governed workspace for maintaining long-term memory.</p>
          <p>Project Memory distills stable decisions, open questions, risks, and next steps from linked evidence.</p>
          <div className="doc-section-actions">
            <Button icon={FileText} label={editingSection === "brief" ? "Close Draft" : "Edit Brief"} onClick={() => {
              setEditingSection((section) => section === "brief" ? null : "brief");
              setNotice("Project Brief draft preview updated");
            }} />
          </div>
          {editingSection === "brief" ? <DraftPreview title="Project Brief draft" /> : null}
        </DocSection>
        <DocSection icon={GitBranch} index="2" title="Current Stage" tag="A3 Calm Operations consolidation">
          <p>Consolidating A3 features and operational flows, refining rebuild and confirmation experiences.</p>
          <div className="doc-section-actions">
            <Button icon={GitCompare} label="Compare with v2" onClick={() => {
              setSelectedVersion("v2");
              setActiveTab("Versions");
              setNotice("Comparing Current Stage with v2");
            }} />
          </div>
        </DocSection>
        <DocSection icon={CircleCheck} index="3" title="Key Decisions">
          <ul>
            <li>Inspector remains a compact preview, not a full detail page.</li>
            <li>Dense audit and evidence move into dedicated detail views.</li>
            <li>Project Memory should read like a maintained document, not a dashboard.</li>
          </ul>
        </DocSection>
        <DocSection icon={CircleAlert} index="4" title="Open Questions">
          <ul className="two-column-list">
            <li>How should automatic pushes into Page Memory be reviewed?<StatusPill label="Open" tone="orange" /></li>
            <li>When should project memory rebuilds be triggered?<StatusPill label="Open" tone="orange" /></li>
            <li>How visible should stale sections become?<StatusPill label="Open" tone="orange" /></li>
          </ul>
        </DocSection>
        <DocSection icon={List} index="5" title="Next Steps">
          <ol className="two-column-list">
            <li>Refine rebuild preview interaction.<StatusPill label="Open" tone="green" /></li>
            <li>Connect linked memory confirmation flow.<StatusPill label="Open" tone="green" /></li>
            <li>Define project memory drift rules.<StatusPill label="Open" tone="green" /></li>
          </ol>
        </DocSection>
        <DocSection icon={Link2} index="6" title="Linked Memories">
          <div className="linked-memory-grid">
            {memories.slice(0, linkedCount).map((memory) => (
              <button key={memory.id} className="linked-memory-card" type="button" onClick={() => setNotice(`${memory.title} selected from linked memories`)}>
                <FileText size={20} />
                <span>{memory.title}</span>
                <small>{memory.source} · 04-27</small>
                <StatusPill label="Active" tone="green" />
              </button>
            ))}
            <button className="link-memory-button" type="button" onClick={() => {
              setLinkedCount((count) => Math.min(memories.length, count + 1));
              setNotice("Linked one additional memory");
            }}>+ Link Memory</button>
          </div>
        </DocSection>
        <DocSection icon={Clock3} index="7" title="Recent Source Events">
          <p>11:32 · Feishu · 产品群 · 用户希望自动维护动作可解释、可撤销</p>
          <p>11:05 · Feishu · 产品群 · 默认关闭 safe_mode，不影响主要使用路径</p>
        </DocSection>
      </article>
      ) : null}
      {activeTab === "Rebuild Preview" ? <ProjectReviewPanel previewState={previewState} onConfirm={confirmPreview} onDiscard={discardPreview} onOpenSources={() => setActiveTab("Sources")} /> : null}
      {activeTab === "Sources" ? <ProjectSourcePanel selectedSource={selectedSource} onSelect={setSelectedSource} onOpen={() => setNotice("Evidence source opened in project preview")} /> : null}
      {activeTab === "Versions" ? <ProjectVersionsPanel selectedVersion={selectedVersion} onSelect={setSelectedVersion} onRestore={(version) => {
        setSelectedVersion(version);
        setNotice(`${version} restore preview opened; current version is not overwritten`);
      }} /> : null}
      {activeTab === "Audit" ? <ProjectAuditPanel activeFilter={auditFilter} onFilter={setAuditFilter} /> : null}
      {activeTab === "Graph" ? <ProjectGraphPanel onOpenTab={(tab, message) => {
        setActiveTab(tab);
        setNotice(message);
      }} /> : null}
    </>
  );
}

function PreviewChange({
  tone,
  title,
  body,
  sources,
}: {
  tone: "success" | "warning" | "danger";
  title: string;
  body: string;
  sources: string;
}) {
  return (
    <div className={`preview-change preview-change--${tone}`}>
      <strong>{title}</strong>
      <p>{body}</p>
      <span>{sources}</span>
    </div>
  );
}

function DraftPreview({ title }: { title: string }) {
  return (
    <div className="draft-preview">
      <strong>{title}</strong>
      <p>Draft changes are staged in the right-side version preview and will only become a project memory version after confirmation.</p>
    </div>
  );
}

function ProjectReviewPanel({
  previewState,
  onConfirm,
  onDiscard,
  onOpenSources,
}: {
  previewState: string;
  onConfirm: () => void;
  onDiscard: () => void;
  onOpenSources: () => void;
}) {
  return (
    <div className="project-tab-panel">
      <div className="section-toolbar section-toolbar--flush">
        <div>
          <h2>Rebuild Candidate Changes</h2>
          <p className="section-subtitle">Candidate changes are staged for review and do not overwrite the current project memory.</p>
        </div>
        <div className="inline-action-row">
          <Button primary icon={Check} label="Confirm Changes" onClick={onConfirm} disabled={previewState !== "pending"} />
          <Button icon={Trash2} label="Discard" onClick={onDiscard} disabled={previewState !== "pending"} />
        </div>
      </div>
      <ProjectRebuildChangeList onOpenSources={onOpenSources} />
      <div className="project-preview-note">
        <CircleAlert size={18} />
        <span>Confirm writes a new `memory_page_versions` candidate later; this UI keeps the current v3 visible until persistence is available.</span>
      </div>
    </div>
  );
}

function ProjectSourcePanel({
  selectedSource,
  onSelect,
  onOpen,
}: {
  selectedSource: string;
  onSelect: (source: string) => void;
  onOpen: () => void;
}) {
  const source = projectSources.find((item) => item.name === selectedSource) ?? projectSources[0];

  return (
    <div className="project-split-panel">
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
        <div className="doc-section-title">
          <Database size={20} />
          <h2>{source.name}</h2>
          <StatusPill label={source.status} tone={source.status === "Linked" ? "green" : "orange"} />
        </div>
        <div className="definition-columns">
          <dl className="definition"><dt>Evidence Count</dt><dd>{source.events}</dd></dl>
          <dl className="definition"><dt>Last Seen</dt><dd>{source.lastSeen}</dd></dl>
          <dl className="definition"><dt>Coverage</dt><dd>{source.coverage}</dd></dl>
          <dl className="definition"><dt>Used For</dt><dd>{source.use}</dd></dl>
        </div>
        <blockquote>“希望自动维护动作可解释，能看到改了哪些关系。”</blockquote>
        <div className="inline-action-row">
          <Button icon={Eye} label="Open Evidence" onClick={onOpen} />
          <Button icon={ShieldCheck} label="Mark Reviewed" onClick={onOpen} />
        </div>
      </article>
    </div>
  );
}

function ProjectVersionsPanel({
  selectedVersion,
  onSelect,
  onRestore,
}: {
  selectedVersion: string;
  onSelect: (version: string) => void;
  onRestore: (version: string) => void;
}) {
  const version = projectVersions.find((item) => item.version === selectedVersion) ?? projectVersions[0];

  return (
    <div className="project-split-panel">
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
        <div className="doc-section-title">
          <History size={20} />
          <h2>{version.version} · {version.summary}</h2>
          <StatusPill label={version.state} tone={version.state === "Current" ? "green" : "gray"} />
        </div>
        <div className="version-diff">
          <div><span>Add</span><p>Next Steps include project memory drift checks.</p></div>
          <div><span>Revise</span><p>Current Stage wording aligned to A3 Calm Operations.</p></div>
          <div><span>Remove</span><p>Older duplicate risk wording removed.</p></div>
        </div>
        <div className="inline-action-row">
          <Button icon={GitCompare} label="Compare" onClick={() => onSelect(version.version)} />
          <Button icon={RefreshCcw} label="Restore Preview" onClick={() => onRestore(version.version)} disabled={version.state === "Current"} />
        </div>
      </article>
    </div>
  );
}

function ProjectAuditPanel({
  activeFilter,
  onFilter,
}: {
  activeFilter: string;
  onFilter: (filter: string) => void;
}) {
  const filters = ["All", "Rebuild", "Evidence", "Version", "Conflict"];
  const visibleEvents = activeFilter === "All" ? auditEvents : auditEvents.filter((event) => event.type === activeFilter);

  return (
    <div className="project-tab-panel">
      <div className="section-toolbar section-toolbar--flush">
        <h2>Audit Events</h2>
        <div className="chip-row">
          {filters.map((filter) => <button key={filter} className={filter === activeFilter ? "is-active" : ""} type="button" onClick={() => onFilter(filter)}>{filter}</button>)}
        </div>
      </div>
      <div className="audit-list">
        {visibleEvents.map((event) => (
          <section key={`${event.time}-${event.title}`} className="audit-row">
            <span>{event.time}</span>
            <StatusPill label={event.type} tone={event.type === "Conflict" ? "red" : event.type === "Rebuild" ? "green" : "orange"} />
            <strong>{event.title}</strong>
            <span>{event.actor}</span>
          </section>
        ))}
      </div>
    </div>
  );
}

function ProjectGraphPanel({ onOpenTab }: { onOpenTab: (tab: string, message: string) => void }) {
  const graphNodes = [
    { label: "Project Memory", meta: "v3 current", target: "Versions", message: "Project Memory version context opened" },
    { label: "Linked Memories", meta: "3 links", target: "Document", message: "Linked memory section opened" },
    { label: "Source Events", meta: "24 events", target: "Sources", message: "Source event evidence opened" },
    { label: "Audit Trail", meta: "5 events", target: "Audit", message: "Audit trail opened from graph" },
    { label: "Rebuild Preview", meta: "3 changes", target: "Rebuild Preview", message: "Rebuild preview opened from graph" },
  ];
  const graphRelations = [
    ["Source Events", "support", "Project Memory", "24 linked"],
    ["Linked Memories", "anchor", "Current Stage", "3 active"],
    ["Rebuild Preview", "proposes", "Project Memory v4", "pending"],
    ["Audit Trail", "records", "Rebuild Preview", "5 events"],
  ];

  return (
    <div className="project-tab-panel">
      <div className="project-graph">
        {graphNodes.map((node, index) => (
          <button key={node.label} type="button" className={`graph-node graph-node--${index}`} onClick={() => onOpenTab(node.target, node.message)}>
            <Network size={18} />
            <strong>{node.label}</strong>
            <span>{node.meta}</span>
          </button>
        ))}
      </div>
      <div className="graph-relation-list">
        <div className="graph-relation-row graph-relation-row--head">
          <span>From</span>
          <span>Relation</span>
          <span>To</span>
          <span>State</span>
        </div>
        {graphRelations.map(([from, relation, to, state]) => (
          <button key={`${from}-${relation}-${to}`} className="graph-relation-row" type="button" onClick={() => onOpenTab(relation === "support" ? "Sources" : "Audit", `${from} relation selected`)}>
            <strong>{from}</strong>
            <span>{relation}</span>
            <span>{to}</span>
            <StatusPill label={state} tone={state === "pending" ? "orange" : "green"} />
          </button>
        ))}
      </div>
      <div className="project-preview-note">
        <Link2 size={18} />
        <span>Compact graph only shows governance relationships. Full transcript and evidence chunks stay in Sources and Audit tabs.</span>
      </div>
    </div>
  );
}
