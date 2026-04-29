import { Archive, Check, Edit3, Eye, EyeOff, Pin } from "lucide-react";
import { Button, Definition, InspectorHeader, InspectorSection, StatusBadge, StrengthMeter, Timeline } from "../../shared/components/ui";
import type { MemoryItem } from "../../shared/types/entities";

export function MemoryInspector({
  memory,
  onOpenDetail,
  onClose,
  libraryMode,
}: {
  memory: MemoryItem;
  onOpenDetail: () => void;
  onClose?: () => void;
  libraryMode?: boolean;
}) {
  return (
    <div className="inspector-panel">
      <InspectorHeader title="Inspector" onOpen={onOpenDetail} onClose={onClose} />
      <h2>{memory.title}</h2>

      <div className="inspector-metrics">
        <Definition label="Lifecycle Status"><StatusBadge status={memory.status} /></Definition>
        <Definition label="Strength"><StrengthMeter value={memory.strength} /></Definition>
      </div>

      <InspectorSection title={libraryMode ? "Why it was kept" : "为何保留"}>
        <p>{memory.reason}</p>
      </InspectorSection>
      <InspectorSection title="Source Preview">
        <p>{memory.source} · 2026-04-27 · 12 messages</p>
        <blockquote>希望自动维护动作可解释，能看到改了哪些关系。</blockquote>
      </InspectorSection>
      <InspectorSection title="Latest Audit Events" action="View all">
        <Timeline rows={["Strength recalculated (0.84)", "Source linked (Feishu · 产品群)", "Evidence updated"]} compact />
      </InspectorSection>
      <div className="action-grid">
        <Button primary icon={Check} label="Confirm" />
        <Button icon={Edit3} label="Edit" />
        <Button icon={Pin} label="Pin" />
        <Button icon={Archive} label="Archive" />
        <Button icon={EyeOff} label="Hide" />
        <Button icon={Eye} label="View Source" />
      </div>
    </div>
  );
}
