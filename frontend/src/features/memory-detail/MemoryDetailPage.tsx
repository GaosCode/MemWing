import { useEffect, useState } from "react";
import { Archive, ArrowLeft, Check, Edit3, Eye, EyeOff, MoreHorizontal, Pin } from "lucide-react";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, StatusBadge, StrengthMeter, Timeline } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
import "./memory-detail.css";
import type { MemoryEditInput } from "../../shared/api/controlPlaneClient";
import type { MemoryDetailDto, MemoryLifecycleAction } from "../../api/generated/controlPlane";
import type { MemoryItem } from "../../shared/types/entities";
import {
  MemoryAudit,
  MemoryEvidence,
  MemoryGraph,
  MemoryOverview,
  MemoryPushes,
  MemoryRecalls,
  MemorySources,
  MemoryVersions,
  memoryTabs,
} from "./MemoryDetailSections";

export function MemoryDetailPage({
  memory,
  detail,
  onBack,
  onLifecycleAction,
  onEditMemory,
}: {
  memory: MemoryItem;
  detail: MemoryDetailDto | null;
  onBack: () => void;
  onLifecycleAction: (memory: MemoryItem, action: MemoryLifecycleAction, reason: string) => Promise<void>;
  onEditMemory: (memory: MemoryItem, input: MemoryEditInput, reason: string) => Promise<void>;
}) {
  const { dictionary } = useI18n();
  const [activeTab, setActiveTab] = useState("Overview");
  const [pinned, setPinned] = useState(memory.flags.includes("pinned"));
  const [lifecycleAction, setLifecycleAction] = useState("Ready for lifecycle review");
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(memory.title);
  const [draftSummary, setDraftSummary] = useState(memory.reason);
  const [draftContent, setDraftContent] = useState(detail?.content ?? memory.reason);

  useEffect(() => {
    setDraftTitle(memory.title);
    setDraftSummary(memory.reason);
    setDraftContent(detail?.content ?? memory.reason);
  }, [detail?.content, memory.id, memory.reason, memory.title]);

  async function confirmMemory() {
    await runLifecycle("confirm", "Memory confirmed for future recall");
  }

  async function togglePin() {
    await runLifecycle(pinned ? "unpin" : "pin", pinned ? "Pin removed" : "Memory pinned");
  }

  function markAction(action: string) {
    setLifecycleAction(action);
  }

  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Queue</button>
          <h1>{memory.title}</h1>
        </div>
        <div className="detail-actions">
          <div className="inline-action-row">
            <Button primary icon={Check} label={dictionary.actions.confirm} onClick={confirmMemory} />
            <Button icon={Edit3} label={dictionary.actions.edit} onClick={() => {
              setEditing((value) => !value);
              markAction(editing ? "Edit draft closed" : "Edit draft opened");
            }} />
            <Button icon={Pin} label={pinned ? dictionary.actions.pinned : dictionary.actions.pin} onClick={togglePin} />
            <Button icon={Eye} label={dictionary.actions.viewSource} onClick={() => setActiveTab("Sources")} />
            <IconButton label={dictionary.common.more} icon={MoreHorizontal} onClick={() => markAction("Memory command menu opened")} />
          </div>
          <div className="danger-row">
            <Button danger icon={Archive} label={dictionary.actions.archive} onClick={() => runLifecycle("archive", "Archive requested; audit remains visible")} />
            <Button danger icon={EyeOff} label={dictionary.actions.hide} onClick={() => runLifecycle("hide", "Memory hidden from default recall preview")} />
          </div>
        </div>
      </header>

      <div className="detail-meta-strip">
        <Definition label="Lifecycle status"><StatusBadge status={memory.status} /></Definition>
        <Definition label="Strength"><StrengthMeter value={memory.strength} /></Definition>
      </div>
      <DetailTabs tabs={memoryTabs} activeTab={activeTab} onSelect={setActiveTab} />
      <div className="notice-row"><Check size={15} />{lifecycleAction}</div>

      <div className="detail-layout">
        <article className="detail-document">
          {editing ? (
            <DocSection icon={Edit3} title="Edit Memory">
              <label className="detail-editor-field">
                <span>Title</span>
                <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} />
              </label>
              <label className="detail-editor-field">
                <span>Summary</span>
                <textarea value={draftSummary} onChange={(event) => setDraftSummary(event.target.value)} />
              </label>
              <label className="detail-editor-field">
                <span>Content</span>
                <textarea value={draftContent} onChange={(event) => setDraftContent(event.target.value)} />
              </label>
              <Button primary icon={Check} label={dictionary.actions.confirm} onClick={saveEdit} />
            </DocSection>
          ) : null}
          {activeTab === "Overview" ? <MemoryOverview memory={memory} detail={detail} /> : null}
          {activeTab === "Sources" ? <MemorySources memory={memory} detail={detail} /> : null}
          {activeTab === "Evidence" ? <MemoryEvidence detail={detail} /> : null}
          {activeTab === "Graph" ? <MemoryGraph detail={detail} /> : null}
          {activeTab === "Versions" ? <MemoryVersions memory={memory} detail={detail} /> : null}
          {activeTab === "Audit" ? <MemoryAudit detail={detail} /> : null}
          {activeTab === "Recalls" ? <MemoryRecalls /> : null}
          {activeTab === "Pushes" ? <MemoryPushes /> : null}
        </article>

        <aside className="detail-side">
          <InspectorSection title="Lifecycle Controls">
            <div className="inline-action-row">
              <Button primary icon={Check} label={dictionary.actions.confirm} onClick={confirmMemory} />
              <Button icon={Edit3} label={dictionary.actions.edit} onClick={() => setEditing((value) => !value)} />
              <Button icon={Pin} label={pinned ? dictionary.actions.pinned : dictionary.actions.pin} onClick={togglePin} />
              <Button icon={Eye} label={dictionary.actions.viewSource} onClick={() => setActiveTab("Sources")} />
            </div>
            <div className="danger-row">
              <Button danger icon={Archive} label={dictionary.actions.archive} onClick={() => runLifecycle("archive", "Archive requested; audit remains visible")} />
              <Button danger icon={EyeOff} label={dictionary.actions.hide} onClick={() => runLifecycle("hide", "Memory hidden from default recall preview")} />
            </div>
          </InspectorSection>
          <InspectorSection title="Metadata">
            <Definition label="Memory ID">{memory.id}</Definition>
            <Definition label="Source IDs">{detail?.source_event_ids.length ?? 0}</Definition>
            <Definition label="Slot Family">User Preference</Definition>
            <Definition label="Visibility">Internal (Project)</Definition>
          </InspectorSection>
          <InspectorSection title="Backend Links" action="View graph" onAction={() => setActiveTab("Graph")}>
            <Timeline rows={[
              `${detail?.graph_links.length ?? 0} graph links`,
              `${detail?.audit_refs.length ?? 0} audit refs`,
              `${detail?.source_event_ids.length ?? 0} source events`,
            ]} compact />
          </InspectorSection>
        </aside>
      </div>
    </section>
  );

  async function runLifecycle(action: MemoryLifecycleAction, successMessage: string) {
    setLifecycleAction("Updating MemWing...");
    try {
      await onLifecycleAction(memory, action, successMessage);
      setPinned(action === "pin" ? true : action === "unpin" ? false : pinned);
      setLifecycleAction(successMessage);
    } catch (error) {
      setLifecycleAction(error instanceof Error ? error.message : "MemWing update failed");
    }
  }

  async function saveEdit() {
    setLifecycleAction("Saving memory edit...");
    try {
      await onEditMemory(
        memory,
        { title: draftTitle, summary: draftSummary, content: draftContent },
        "用户编辑并确认这条记忆内容",
      );
      setEditing(false);
      setLifecycleAction("Memory edit saved");
    } catch (error) {
      setLifecycleAction(error instanceof Error ? error.message : "MemWing edit failed");
    }
  }
}
