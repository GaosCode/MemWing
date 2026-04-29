import { useState } from "react";
import { Archive, ArrowLeft, Check, CircleAlert, Database, Edit3, Eye, EyeOff, FileText, GitBranch, Link2, MoreHorizontal, Pin, RotateCcw } from "lucide-react";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, StatusBadge, StatusPill, StrengthMeter, Timeline } from "../../shared/components/ui";
import type { MemoryItem } from "../../shared/types/entities";

const memoryTabs = ["Overview", "Sources", "Evidence", "Graph", "Versions", "Audit", "Recalls", "Pushes"];

export function MemoryDetailPage({ memory, onBack }: { memory: MemoryItem; onBack: () => void }) {
  const [activeTab, setActiveTab] = useState("Overview");
  const [pinned, setPinned] = useState(memory.flags.includes("pinned"));
  const [lifecycleAction, setLifecycleAction] = useState("Ready for lifecycle review");

  function confirmMemory() {
    setLifecycleAction("Memory confirmed for future recall");
  }

  function togglePin() {
    setPinned((value) => !value);
    setLifecycleAction(pinned ? "Pin removed" : "Memory pinned");
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
            <Button primary icon={Check} label="Confirm" onClick={confirmMemory} />
            <Button icon={Edit3} label="Edit" onClick={() => markAction("Edit draft opened")} />
            <Button icon={Pin} label={pinned ? "Pinned" : "Pin"} onClick={togglePin} />
            <Button icon={Eye} label="View Source" onClick={() => setActiveTab("Sources")} />
            <IconButton label="More" icon={MoreHorizontal} onClick={() => markAction("Memory command menu opened")} />
          </div>
          <div className="danger-row">
            <Button danger icon={Archive} label="Archive" onClick={() => markAction("Archive requested; audit remains visible")} />
            <Button danger icon={EyeOff} label="Hide" onClick={() => markAction("Memory hidden from default recall preview")} />
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
          {activeTab === "Overview" ? <MemoryOverview memory={memory} /> : null}
          {activeTab === "Sources" ? <MemorySources memory={memory} /> : null}
          {activeTab === "Evidence" ? <MemoryEvidence /> : null}
          {activeTab === "Graph" ? <MemoryGraph /> : null}
          {activeTab === "Versions" ? <MemoryVersions memory={memory} /> : null}
          {activeTab === "Audit" ? <MemoryAudit /> : null}
          {activeTab === "Recalls" ? <MemoryRecalls /> : null}
          {activeTab === "Pushes" ? <MemoryPushes /> : null}
        </article>

        <aside className="detail-side">
          <InspectorSection title="Lifecycle Controls">
            <div className="inline-action-row">
              <Button primary icon={Check} label="Confirm" onClick={confirmMemory} />
              <Button icon={Edit3} label="Edit" onClick={() => markAction("Edit draft opened")} />
              <Button icon={Pin} label={pinned ? "Pinned" : "Pin"} onClick={togglePin} />
              <Button icon={Eye} label="View Source" onClick={() => setActiveTab("Sources")} />
            </div>
            <div className="danger-row">
              <Button danger icon={Archive} label="Archive" onClick={() => markAction("Archive requested; audit remains visible")} />
              <Button danger icon={EyeOff} label="Hide" onClick={() => markAction("Memory hidden from default recall preview")} />
            </div>
          </InspectorSection>
          <InspectorSection title="Metadata">
            <Definition label="Memory ID">mem_q813vK9XP87BQx9H2OV5z1BEYC</Definition>
            <Definition label="Source ID">src_feishu_20260427_10_15_7823</Definition>
            <Definition label="Slot Family">User Preference</Definition>
            <Definition label="Visibility">Internal (Project)</Definition>
          </InspectorSection>
          <InspectorSection title="Versions (3)" action="View all" onAction={() => setActiveTab("Versions")}>
            <Timeline rows={["v3 current · 0.84 · 2026-04-27 11:32", "v2 · 0.71 · 2026-04-27 11:05", "v1 · 0.53 · 2026-04-27 10:15"]} compact />
          </InspectorSection>
        </aside>
      </div>
    </section>
  );
}

function MemoryOverview({ memory }: { memory: MemoryItem }) {
  return (
    <>
      <DocSection icon={FileText} index="1" title="Current Memory">
        <p>用户希望自动维护动作（如合并、去重、重写、归档）具备可解释性，并支持撤销操作，以便在发生误判时能够回溯或恢复，降低维护风险并建立信任。</p>
      </DocSection>
      <DocSection icon={CircleAlert} index="2" title="Why It Was Kept">
        <p>{memory.reason}</p>
      </DocSection>
      <DocSection icon={Link2} index="3" title="Linked Page Memory">
        <div className="linked-page">
          <FileText size={26} />
          <div>
            <strong>自动化维护能力 & 机制设计（规划）</strong>
            <p>/ Products / AI Memory / Governance</p>
          </div>
          <StatusPill label="Active" tone="green" />
        </div>
      </DocSection>
      <DocSection icon={Database} index="4" title="Forgetting Curve">
        <div className="definition-columns">
          <Definition label="Decay score">{memory.forgetting.decayScore.toFixed(2)}</Definition>
          <Definition label="Last reinforced">{memory.forgetting.lastReinforcedAt.slice(0, 16)}</Definition>
          <Definition label="Next review">{memory.forgetting.nextReviewAt}</Definition>
          <Definition label="Curve state"><StatusPill label={memory.forgetting.curveState.replace(/_/g, " ")} tone={memory.forgetting.curveState === "ready_to_forget" ? "orange" : "green"} /></Definition>
        </div>
      </DocSection>
      <DocSection icon={FileText} index="5" title="Evidence Summary">
        <blockquote className="evidence-block">希望自动维护动作可解释，能看到改了哪些关系。如果误删了对，应该可以一键撤销或恢复到之前状态。</blockquote>
      </DocSection>
    </>
  );
}

function MemorySources({ memory }: { memory: MemoryItem }) {
  return (
    <>
      <DocSection icon={Database} title="Source & Purge State">
        <div className="definition-columns">
          <Definition label="Source">Feishu · 产品群 · 2026-04-27 · 12 messages</Definition>
          <Definition label="Purge state"><StatusPill label="Not purged" tone="green" /></Definition>
          <Definition label="Redaction state"><StatusPill label="Not triggered" tone="green" /></Definition>
          <Definition label="Retention reason">{memory.forgetting.retentionReason}</Definition>
        </div>
      </DocSection>
      <DocSection icon={Link2} title="Linked Sources">
        <div className="timeline-board">
          {["Feishu · 产品群 · planning thread", "Page Memory · governance section", "Audit event · strength recalculated"].map((row) => (
            <section className="timeline-card" key={row}>
              <span>Linked</span>
              <strong>{row}</strong>
              <p>Available for source preview and audit reconstruction.</p>
            </section>
          ))}
        </div>
      </DocSection>
    </>
  );
}

function MemoryEvidence() {
  return (
    <DocSection icon={FileText} title="Evidence Preview">
      <blockquote className="evidence-block">“希望自动维护动作可解释，能看到改了哪些关系。”</blockquote>
      <blockquote className="evidence-block">“如果误删了对，应该可以一键撤销或恢复到之前状态。”</blockquote>
    </DocSection>
  );
}

function MemoryGraph() {
  return (
    <DocSection icon={GitBranch} title="Graph Links">
      <div className="memory-board memory-board--compact">
        {["Preference", "Project Memory", "Audit Event"].map((node) => (
          <section className="board-card" key={node}>
            <strong>{node}</strong>
            <p>Linked through current memory evidence.</p>
          </section>
        ))}
      </div>
    </DocSection>
  );
}

function MemoryVersions({ memory }: { memory: MemoryItem }) {
  return (
    <DocSection icon={RotateCcw} title="Version Timeline">
      <Timeline rows={[
        `v3 current · ${memory.strength.toFixed(2)} · 2026-04-27 11:32`,
        "v2 · 0.71 · 2026-04-27 11:05",
        "v1 · 0.53 · 2026-04-27 10:15",
      ]} />
    </DocSection>
  );
}

function MemoryAudit() {
  return (
    <DocSection icon={CircleAlert} title="Audit Trail">
      <Timeline rows={["11:32 Strength recalculated", "11:21 Evidence linked", "10:33 Source preview updated"]} />
    </DocSection>
  );
}

function MemoryRecalls() {
  return (
    <DocSection icon={Eye} title="Recent Recalls">
      <Timeline rows={["2026-04-27 13:12 Planning_Auto-maintain UX discussion", "2026-04-26 18:44 Preference recall: Governance UI"]} />
    </DocSection>
  );
}

function MemoryPushes() {
  return (
    <DocSection icon={Archive} title="Recent Pushes">
      <Timeline rows={["2026-04-27 12:45 Pushed to Page Memory: 自动化维护能力 & 机制设计（规划）"]} />
    </DocSection>
  );
}
