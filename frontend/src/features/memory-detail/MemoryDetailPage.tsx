import { Archive, ArrowLeft, Check, CircleAlert, Database, Edit3, Eye, EyeOff, FileText, Link2, MoreHorizontal, Pin } from "lucide-react";
import { Button, Definition, DetailTabs, DocSection, IconButton, InspectorSection, StatusBadge, StatusPill, StrengthMeter, Timeline } from "../../shared/components/ui";
import type { MemoryItem } from "../../shared/types/entities";

export function MemoryDetailPage({ memory, onBack }: { memory: MemoryItem; onBack: () => void }) {
  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Queue</button>
          <h1>{memory.title}</h1>
        </div>
        <div className="detail-actions">
          <div className="inline-action-row">
            <Button primary icon={Check} label="Confirm" />
            <Button icon={Edit3} label="Edit" />
            <Button icon={Pin} label="Pin" />
            <Button icon={Eye} label="View Source" />
            <IconButton label="More" icon={MoreHorizontal} />
          </div>
          <div className="danger-row">
            <Button danger icon={Archive} label="Archive" />
            <Button danger icon={EyeOff} label="Hide" />
          </div>
        </div>
      </header>

      <div className="detail-meta-strip">
        <Definition label="Lifecycle status"><StatusBadge status={memory.status} /></Definition>
        <Definition label="Strength"><StrengthMeter value={memory.strength} /></Definition>
      </div>
      <DetailTabs tabs={["Overview", "Sources", "Evidence", "Graph", "Versions", "Audit", "Recalls", "Pushes"]} />

      <div className="detail-layout">
        <article className="detail-document">
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
          <DocSection icon={Database} index="4" title="Source & Purge State">
            <div className="definition-columns">
              <Definition label="Source">Feishu · 产品群 · 2026-04-27 · 12 messages</Definition>
              <Definition label="Purge state"><StatusPill label="Not purged" tone="green" /></Definition>
              <Definition label="Redaction state"><StatusPill label="Not triggered" tone="green" /></Definition>
              <Definition label="TTL">—</Definition>
            </div>
          </DocSection>
          <DocSection icon={FileText} index="5" title="Evidence Summary">
            <blockquote className="evidence-block">希望自动维护动作可解释，能看到改了哪些关系。如果误删了对，应该可以一键撤销或恢复到之前状态。</blockquote>
          </DocSection>
        </article>

        <aside className="detail-side">
          <InspectorSection title="Lifecycle Controls">
            <div className="inline-action-row">
              <Button primary icon={Check} label="Confirm" />
              <Button icon={Edit3} label="Edit" />
              <Button icon={Pin} label="Pin" />
              <Button icon={Eye} label="View Source" />
            </div>
            <div className="danger-row">
              <Button danger icon={Archive} label="Archive" />
              <Button danger icon={EyeOff} label="Hide" />
            </div>
          </InspectorSection>
          <InspectorSection title="Metadata">
            <Definition label="Memory ID">mem_q813vK9XP87BQx9H2OV5z1BEYC</Definition>
            <Definition label="Source ID">src_feishu_20260427_10_15_7823</Definition>
            <Definition label="Slot Family">User Preference</Definition>
            <Definition label="Visibility">Internal (Project)</Definition>
          </InspectorSection>
          <InspectorSection title="Versions (3)" action="View all">
            <Timeline rows={["v3 current · 0.84 · 2026-04-27 11:32", "v2 · 0.71 · 2026-04-27 11:05", "v1 · 0.53 · 2026-04-27 10:15"]} compact />
          </InspectorSection>
        </aside>
      </div>
    </section>
  );
}
