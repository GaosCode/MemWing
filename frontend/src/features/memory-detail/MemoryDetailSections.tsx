import {
  Archive,
  CircleAlert,
  Database,
  Eye,
  FileText,
  GitBranch,
  Link2,
  RotateCcw,
} from "lucide-react";
import { Definition, DocSection, StatusPill, Timeline } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
import type { MemoryDetailDto } from "../../api/generated/controlPlane";
import type { MemoryItem } from "../../shared/types/entities";

export const memoryTabs = ["Overview", "Sources", "Evidence", "Graph", "Versions", "Audit", "Recalls", "Pushes"];

export function MemoryOverview({ memory, detail }: { memory: MemoryItem; detail: MemoryDetailDto | null }) {
  const { dictionary } = useI18n();
  return (
    <>
      <DocSection icon={FileText} index="1" title="Current Memory">
        <p>{detail?.content ?? memory.reason}</p>
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
          <StatusPill label={dictionary.status.lifecycle.active.label} tone="green" />
        </div>
      </DocSection>
      <DocSection icon={Database} index="4" title="Forgetting Curve">
        <div className="definition-columns">
          <Definition label="Decay score">{memory.forgetting.decayScore.toFixed(2)}</Definition>
          <Definition label="Last reinforced">{memory.forgetting.lastReinforcedAt.slice(0, 16)}</Definition>
          <Definition label="Next review">{memory.forgetting.nextReviewAt ?? "none"}</Definition>
          <Definition label="Curve state"><StatusPill label={memory.forgetting.curveState.replace(/_/g, " ")} tone={memory.forgetting.curveState === "below_threshold" ? "orange" : "green"} /></Definition>
        </div>
      </DocSection>
      <DocSection icon={FileText} index="5" title="Evidence Summary">
        <blockquote className="evidence-block">希望自动维护动作可解释，能看到改了哪些关系。如果误删了对，应该可以一键撤销或恢复到之前状态。</blockquote>
      </DocSection>
    </>
  );
}

export function MemorySources({ memory, detail }: { memory: MemoryItem; detail: MemoryDetailDto | null }) {
  return (
    <>
      <DocSection icon={Database} title="Source & Purge State">
        <div className="definition-columns">
          <Definition label="Source">{memory.source}</Definition>
          <Definition label="Purge state"><StatusPill label={memory.flags.includes("source_redacted") ? "Redacted" : "Not purged"} tone={memory.flags.includes("source_redacted") ? "orange" : "green"} /></Definition>
          <Definition label="Redaction state"><StatusPill label={memory.flags.includes("source_redacted") ? "Graph raw retained" : "Not triggered"} tone={memory.flags.includes("source_redacted") ? "orange" : "green"} /></Definition>
          <Definition label="Retention reason">{memory.forgetting.retentionReason}</Definition>
        </div>
      </DocSection>
      <DocSection icon={Link2} title="Linked Sources">
        <div className="timeline-board">
          {detail?.source_event_ids.length ? detail.source_event_ids.map((sourceEventId) => (
            <section className="timeline-card" key={sourceEventId}>
              <span>source_event</span>
              <strong>{sourceEventId}</strong>
              <p>Loaded from backend memory detail.</p>
            </section>
          )) : memory.flags.length === 0 ? (
            <section className="timeline-card">
              <span>Linked</span>
              <strong>{memory.source}</strong>
              <p>Available for source preview and audit reconstruction.</p>
            </section>
          ) : memory.flags.map((flag) => (
            <section className="timeline-card" key={flag}>
              <span>Flag</span>
              <strong>{flag}</strong>
              <p>Shown from backend-derived memory flags.</p>
            </section>
          ))}
        </div>
      </DocSection>
    </>
  );
}

export function MemoryEvidence({ detail }: { detail: MemoryDetailDto | null }) {
  return (
    <DocSection icon={FileText} title="Evidence Preview">
      {detail?.source_event_ids.length ? detail.source_event_ids.map((sourceEventId) => (
        <blockquote key={sourceEventId} className="evidence-block">source_events · {sourceEventId}</blockquote>
      )) : <blockquote className="evidence-block">Evidence is resolved from linked source events in the backend detail response.</blockquote>}
    </DocSection>
  );
}

export function MemoryGraph({ detail }: { detail: MemoryDetailDto | null }) {
  const links = detail?.graph_links ?? [];
  return (
    <DocSection icon={GitBranch} title="Graph Links">
      <div className="memory-board memory-board--compact">
        {links.map((link) => (
          <section className="board-card" key={link.id}>
            <strong>{link.backend_object_type}</strong>
            <p>{link.link_type} · {link.backend}</p>
            <span>{link.backend_object_id}</span>
          </section>
        ))}
        {links.length === 0 ? (
          <section className="board-card">
            <strong>No graph links</strong>
            <p>The backend detail response did not return graph links for this memory.</p>
          </section>
        ) : null}
      </div>
    </DocSection>
  );
}

export function MemoryVersions({ memory, detail }: { memory: MemoryItem; detail: MemoryDetailDto | null }) {
  return (
    <DocSection icon={RotateCcw} title="Version Timeline">
      <Timeline rows={[
        `current · ${memory.strength.toFixed(2)} · ${memory.lastSeen.slice(0, 16)}`,
        `${detail?.memory_item_ids.length ?? 1} memory item ids linked in detail`,
      ]} />
    </DocSection>
  );
}

export function MemoryAudit({ detail }: { detail: MemoryDetailDto | null }) {
  return (
    <DocSection icon={CircleAlert} title="Audit Trail">
      <Timeline rows={detail?.audit_refs.length ? detail.audit_refs : ["Audit references are returned by the backend memory detail endpoint."]} />
    </DocSection>
  );
}

export function MemoryRecalls() {
  return (
    <DocSection icon={Eye} title="Recent Recalls">
      <Timeline rows={["Recall history is reserved for the backend recall-events endpoint."]} />
    </DocSection>
  );
}

export function MemoryPushes() {
  return (
    <DocSection icon={Archive} title="Recent Pushes">
      <Timeline rows={["Push candidates are managed from Maintenance and linked back to this memory."]} />
    </DocSection>
  );
}
