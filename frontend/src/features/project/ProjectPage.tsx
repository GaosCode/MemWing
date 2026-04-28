import { CircleAlert, CircleCheck, Clock3, FileText, GitBranch, Link2, List, MoreHorizontal } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { DocSection, IconButton, PageHeader, StatusPill } from "../../shared/components/ui";

export function ProjectPage() {
  return (
    <>
      <PageHeader
        title="Project Memory"
        subtitle="Maintain the project-level Page Memory with evidence-backed edits and rebuild previews."
        actions={
          <>
            <span className="header-meta">Last rebuilt: 2026-04-27 11:32</span>
            <span className="header-meta">v3 current</span>
            <IconButton label="More" icon={MoreHorizontal} />
          </>
        }
      />

      <div className="rebuild-band">
        <div>
          <strong>Rebuild Preview</strong>
          <span className="outline-chip">3 changes</span>
          <p>Review candidate changes before confirming to the project memory.</p>
        </div>
        <PreviewChange tone="success" title="Add" body="Next Steps now include project memory drift checks." sources="2 sources" />
        <PreviewChange tone="warning" title="Revise" body="Current Stage updated to A3 Calm Operations consolidation." sources="3 sources" />
        <PreviewChange tone="danger" title="Remove" body="Older duplicate risk wording removed." sources="1 source" />
      </div>

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
            {memories.slice(0, 3).map((memory) => (
              <button key={memory.id} className="linked-memory-card">
                <FileText size={20} />
                <span>{memory.title}</span>
                <small>{memory.source} · 04-27</small>
                <StatusPill label="Active" tone="green" />
              </button>
            ))}
            <button className="link-memory-button">+ Link Memory</button>
          </div>
        </DocSection>
        <DocSection icon={Clock3} index="7" title="Recent Source Events">
          <p>11:32 · Feishu · 产品群 · 用户希望自动维护动作可解释、可撤销</p>
          <p>11:05 · Feishu · 产品群 · 默认关闭 safe_mode，不影响主要使用路径</p>
        </DocSection>
      </article>
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
