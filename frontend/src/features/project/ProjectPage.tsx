import { useEffect, useMemo, useState } from "react";
import { Check, MoreHorizontal, RefreshCcw, ShieldCheck } from "lucide-react";
import { Button, DetailTabs, IconButton, PageHeader, StatusPill } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
import type { PageEditInput } from "../../shared/api/controlPlaneClient";
import type { MemoryItem } from "../../shared/types/entities";
import type { ControlPageDetailDto, ControlPageDto } from "../../api/generated/controlPlane";
import { ProjectDocument } from "./ProjectDocument";
import {
  ProjectAuditPanel,
  ProjectGraphPanel,
  ProjectReviewPanel,
  ProjectSourcePanel,
  ProjectVersionsPanel,
} from "./ProjectPanels";

const projectTabs = ["Document", "Rebuild Preview", "Sources", "Versions", "Audit", "Graph"];

export function ProjectPage({
  page,
  detail,
  memories,
  onSelectMemory,
  onRebuildPage,
  onEditPage,
  onRestorePageVersion,
}: {
  page: ControlPageDto;
  detail: ControlPageDetailDto | null;
  memories: MemoryItem[];
  onSelectMemory: (memory: MemoryItem) => void;
  onRebuildPage: (page: ControlPageDto) => Promise<void>;
  onEditPage: (page: ControlPageDto, input: PageEditInput, reason: string) => Promise<void>;
  onRestorePageVersion: (page: ControlPageDto, version: number) => Promise<void>;
}) {
  const { dictionary } = useI18n();
  const [activeTab, setActiveTab] = useState("Document");
  const [editingBrief, setEditingBrief] = useState(false);
  const [draftBrief, setDraftBrief] = useState(page.brief);
  const [selectedSource, setSelectedSource] = useState<string>(page.source_event_ids[0] ?? "none");
  const [selectedVersion, setSelectedVersion] = useState(page.version);
  const [auditFilter, setAuditFilter] = useState("All");
  const [notice, setNotice] = useState("Page Memory loaded from backend");
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    setDraftBrief(page.brief);
    setSelectedSource(page.source_event_ids[0] ?? "none");
    setSelectedVersion(page.version);
  }, [page.brief, page.id, page.source_event_ids, page.version]);

  const linkedMemories = useMemo(
    () => page.linked_memory_item_ids
      .map((memoryId) => memories.find((memory) => memory.id === memoryId))
      .filter((memory): memory is MemoryItem => memory !== undefined),
    [memories, page.linked_memory_item_ids],
  );

  async function runAction(action: () => Promise<void>, successNotice: string) {
    setUpdating(true);
    setNotice("Sending request to MemWing backend");
    try {
      await action();
      setNotice(successNotice);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "MemWing API request failed");
    } finally {
      setUpdating(false);
    }
  }

  function saveBrief() {
    void runAction(
      () => onEditPage(page, { title: page.title, brief: draftBrief }, "frontend project brief edit"),
      "Project brief saved and version history refreshed",
    );
    setEditingBrief(false);
  }

  function runRebuild() {
    void runAction(
      () => onRebuildPage(page),
      "Page Memory rebuild completed and refreshed from backend",
    );
    setActiveTab("Versions");
  }

  function restoreVersion(version: number) {
    void runAction(
      () => onRestorePageVersion(page, version),
      `v${version} restored through Control Plane`,
    );
    setActiveTab("Versions");
  }

  return (
    <>
      <PageHeader
        title="Project Memory"
        subtitle="Maintain the project-level Page Memory with evidence-backed edits and backend rebuilds."
        actions={
          <>
            <span className="header-meta">Last rebuilt: {page.updated_at}</span>
            <StatusPill label={page.needs_rebuild ? "needs rebuild" : `v${page.version} current`} tone={page.needs_rebuild ? "orange" : "green"} />
            <Button icon={RefreshCcw} label={updating ? "Running" : "Run Rebuild"} onClick={runRebuild} disabled={updating} />
            <IconButton label={dictionary.common.more} icon={MoreHorizontal} onClick={() => setNotice(`trace ${detail?.trace_id ?? "not loaded"}`)} />
          </>
        }
      />

      {page.needs_rebuild || page.warning_count > 0 ? (
        <div className="rebuild-band">
          <div>
            <strong>Rebuild Review</strong>
            <span className="outline-chip">{page.warning_count} warnings</span>
            <p>{page.needs_rebuild ? "The backend marked this Page Memory as needing a rebuild." : "Linked sources include governance warnings."}</p>
            <div className="inline-action-row">
              <Button primary icon={RefreshCcw} label="Run Rebuild" onClick={runRebuild} disabled={updating} />
              <Button icon={ShieldCheck} label="Open Sources" onClick={() => setActiveTab("Sources")} />
            </div>
          </div>
          {page.topics.slice(0, 3).map((topic) => (
            <div key={topic.title} className="preview-change preview-change--success">
              <strong>{topic.title}</strong>
              <p>{topic.summary}</p>
              <span>{topic.source_event_ids.length} sources</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="project-state-band">
          <span><ShieldCheck size={17} />Rebuild State</span>
          <strong>Backend projection is current</strong>
          <p>No rebuild requirement is currently reported for this Page Memory scope.</p>
          <Button icon={RefreshCcw} label="Run Rebuild" onClick={runRebuild} disabled={updating} />
        </div>
      )}

      <DetailTabs tabs={projectTabs} activeTab={activeTab} onSelect={setActiveTab} />
      <div className="notice-row"><Check size={15} />{notice}</div>

      {activeTab === "Document" ? (
        <ProjectDocument
          page={page}
          linkedMemories={linkedMemories}
          editingBrief={editingBrief}
          draftBrief={draftBrief}
          onDraftBrief={setDraftBrief}
          onToggleBrief={() => setEditingBrief((value) => !value)}
          onSaveBrief={saveBrief}
          onOpenVersions={() => setActiveTab("Versions")}
          onOpenMemory={onSelectMemory}
        />
      ) : null}
      {activeTab === "Rebuild Preview" ? <ProjectReviewPanel page={page} updating={updating} onRebuild={runRebuild} onOpenSources={() => setActiveTab("Sources")} /> : null}
      {activeTab === "Sources" ? <ProjectSourcePanel page={page} selectedSource={selectedSource} onSelect={setSelectedSource} onOpen={() => setNotice("Evidence source selected from backend source_event_ids")} /> : null}
      {activeTab === "Versions" ? (
        <ProjectVersionsPanel
          page={page}
          detail={detail}
          selectedVersion={selectedVersion}
          updating={updating}
          onSelect={setSelectedVersion}
          onRestore={restoreVersion}
        />
      ) : null}
      {activeTab === "Audit" ? <ProjectAuditPanel detail={detail} activeFilter={auditFilter} onFilter={setAuditFilter} /> : null}
      {activeTab === "Graph" ? (
        <ProjectGraphPanel
          page={page}
          linkedMemories={linkedMemories}
          onOpenTab={(tab, message) => {
            setActiveTab(tab);
            setNotice(message);
          }}
        />
      ) : null}
    </>
  );
}
