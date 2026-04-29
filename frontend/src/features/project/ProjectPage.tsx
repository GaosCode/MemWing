import { useState } from "react";
import { Check, CircleAlert, CircleCheck, Clock3, Eye, FileText, GitBranch, Link2, List, MoreHorizontal, Trash2 } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { Button, DetailTabs, DocSection, IconButton, PageHeader, StatusPill } from "../../shared/components/ui";

const projectTabs = ["Document", "Rebuild Preview", "Sources", "Versions", "Audit"];

export function ProjectPage() {
  const [activeTab, setActiveTab] = useState("Document");
  const [previewState, setPreviewState] = useState<"pending" | "confirmed" | "discarded">("pending");
  const [linkedCount, setLinkedCount] = useState(3);
  const [notice, setNotice] = useState("Rebuild preview is pending review");

  return (
    <>
      <PageHeader
        title="Project Memory"
        subtitle="Maintain the project-level Page Memory with evidence-backed edits and rebuild previews."
        actions={
          <>
            <span className="header-meta">Last rebuilt: 2026-04-27 11:32</span>
            <StatusPill label={previewState === "confirmed" ? "v4 preview confirmed" : "v3 current"} tone={previewState === "confirmed" ? "green" : "orange"} />
            <IconButton label="More" icon={MoreHorizontal} onClick={() => setNotice("Project command menu opened")} />
          </>
        }
      />

      <div className="rebuild-band">
        <div>
          <strong>Rebuild Preview</strong>
          <span className="outline-chip">{previewState === "pending" ? "3 changes" : previewState}</span>
          <p>{previewState === "pending" ? "Review candidate changes before confirming to the project memory." : "Preview state has been updated locally for this session."}</p>
          <div className="inline-action-row">
            <Button primary icon={Check} label="Confirm" onClick={() => {
              setPreviewState("confirmed");
              setNotice("Rebuild changes confirmed");
            }} />
            <Button icon={Trash2} label="Discard" onClick={() => {
              setPreviewState("discarded");
              setNotice("Rebuild changes discarded");
            }} />
          </div>
        </div>
        <PreviewChange tone="success" title="Add" body="Next Steps now include project memory drift checks." sources="2 sources" />
        <PreviewChange tone="warning" title="Revise" body="Current Stage updated to A3 Calm Operations consolidation." sources="3 sources" />
        <PreviewChange tone="danger" title="Remove" body="Older duplicate risk wording removed." sources="1 source" />
      </div>

      <DetailTabs tabs={projectTabs} activeTab={activeTab} onSelect={setActiveTab} />
      <div className="notice-row"><Check size={15} />{notice}</div>

      {activeTab === "Document" ? (
      <article className="document-workbench">
        <DocSection icon={FileText} index="1" title="Project Brief">
          <p>MemWing provides a governed workspace for maintaining long-term memory.</p>
          <p>Project Memory distills stable decisions, open questions, risks, and next steps from linked evidence.</p>
        </DocSection>
        <DocSection icon={GitBranch} index="2" title="Current Stage" tag="A3 Calm Operations consolidation">
          <p>Consolidating A3 features and operational flows, refining rebuild and confirmation experiences.</p>
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
      {activeTab === "Rebuild Preview" ? <ProjectReviewPanel previewState={previewState} /> : null}
      {activeTab === "Sources" ? <ProjectSourcePanel onOpen={() => setNotice("Evidence source opened in project preview")} /> : null}
      {activeTab === "Versions" ? <ProjectVersionsPanel /> : null}
      {activeTab === "Audit" ? <ProjectAuditPanel /> : null}
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

function ProjectReviewPanel({ previewState }: { previewState: string }) {
  return (
    <div className="overview-grid">
      {[
        ["Add", "Next Steps include project memory drift checks.", "2 sources"],
        ["Revise", "Current Stage wording moves to A3 Calm Operations.", "3 sources"],
        ["Remove", "Older duplicate risk wording is retired.", "1 source"],
      ].map(([type, body, sources]) => (
        <section key={type} className="overview-panel">
          <span>{type}</span>
          <strong>{sources}</strong>
          <p>{body}</p>
          <StatusPill label={previewState} tone={previewState === "confirmed" ? "green" : "orange"} />
        </section>
      ))}
    </div>
  );
}

function ProjectSourcePanel({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="timeline-board">
      {["Feishu · 产品群 · 14 events", "Feishu · 安全群 · 5 events", "AI 产品自动化维护 · 3 events"].map((row) => (
        <section key={row} className="timeline-card">
          <span>Source</span>
          <strong>{row}</strong>
          <p>Evidence is linked and available for audit.</p>
          <Button icon={Eye} label="Open Evidence" onClick={onOpen} />
        </section>
      ))}
    </div>
  );
}

function ProjectVersionsPanel() {
  return (
    <div className="timeline-board">
      {["v3 current · 2026-04-27 11:32", "v2 · 2026-04-27 11:05", "v1 · 2026-04-27 10:15"].map((row) => (
        <section key={row} className="timeline-card">
          <span>Version</span>
          <strong>{row}</strong>
          <p>Open to inspect rebuild diff and source coverage.</p>
        </section>
      ))}
    </div>
  );
}

function ProjectAuditPanel() {
  return (
    <div className="timeline-board">
      {["Rebuild preview generated", "Project stage revised", "Conflict scan completed", "Initial project memory captured"].map((row, index) => (
        <section key={row} className="timeline-card">
          <span>{`11:${32 - index * 9}`}</span>
          <strong>{row}</strong>
          <p>Audit event is linked to current project memory version.</p>
        </section>
      ))}
    </div>
  );
}
