import { useEffect, useState } from "react";
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
  const [pinned, setPinned] = useState(memory.flags.includes("pinned"));
  const [notice, setNotice] = useState("Inspector ready");

  useEffect(() => {
    setPinned(memory.flags.includes("pinned"));
    setNotice("Inspector ready");
  }, [memory.id, memory.flags]);

  return (
    <div className="inspector-panel">
      <InspectorHeader title="Inspector" onOpen={onOpenDetail} onClose={onClose} pinned={pinned} onPin={() => {
        setPinned((value) => !value);
        setNotice(pinned ? "Pin removed" : "Memory pinned");
      }} />
      <h2>{memory.title}</h2>
      <div className="inspector-notice">{notice}</div>

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
      <InspectorSection title="Latest Audit Events" action="View all" onAction={() => setNotice("Audit events opened in detail preview")}>
        <Timeline rows={["Strength recalculated (0.84)", "Source linked (Feishu · 产品群)", "Evidence updated"]} compact />
      </InspectorSection>
      <div className="action-grid">
        <Button primary icon={Check} label="Confirm" onClick={() => setNotice("Memory confirmed")} />
        <Button icon={Edit3} label="Edit" onClick={() => setNotice("Edit draft opened")} />
        <Button icon={Pin} label={pinned ? "Pinned" : "Pin"} onClick={() => {
          setPinned((value) => !value);
          setNotice(pinned ? "Pin removed" : "Memory pinned");
        }} />
        <Button icon={Archive} label="Archive" onClick={() => setNotice("Archive requested")} />
        <Button icon={EyeOff} label="Hide" onClick={() => setNotice("Memory hidden from default recall")} />
        <Button icon={Eye} label="View Source" onClick={onOpenDetail} />
      </div>
    </div>
  );
}
