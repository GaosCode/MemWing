import { useEffect, useState } from "react";
import { Archive, Check, Edit3, Eye, EyeOff, Pin } from "lucide-react";
import { Button, Definition, InspectorHeader, InspectorSection, StatusBadge, StrengthMeter, Timeline } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
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
  const { dictionary } = useI18n();
  const [pinned, setPinned] = useState(memory.flags.includes("pinned"));
  const [notice, setNotice] = useState(dictionary.inspector.ready);

  useEffect(() => {
    setPinned(memory.flags.includes("pinned"));
    setNotice(dictionary.inspector.ready);
  }, [dictionary.inspector.ready, memory.id, memory.flags]);

  return (
    <div className="inspector-panel">
      <InspectorHeader title={dictionary.inspector.memoryTitle} onOpen={onOpenDetail} onClose={onClose} pinned={pinned} onPin={() => {
        setPinned((value) => !value);
        setNotice(pinned ? dictionary.inspector.pinRemoved : dictionary.inspector.memoryPinned);
      }} />
      <h2>{memory.title}</h2>
      <div className="inspector-notice">{notice}</div>

      <div className="inspector-metrics">
        <Definition label={dictionary.inspector.lifecycleStatus}><StatusBadge status={memory.status} /></Definition>
        <Definition label={dictionary.inspector.strength}><StrengthMeter value={memory.strength} /></Definition>
      </div>

      <InspectorSection title={dictionary.inspector.whyKept}>
        <p>{memory.reason}</p>
      </InspectorSection>
      <InspectorSection title={dictionary.inspector.sourcePreview}>
        <p>{memory.source} · 2026-04-27 · 12 messages</p>
        <blockquote>希望自动维护动作可解释，能看到改了哪些关系。</blockquote>
      </InspectorSection>
      <InspectorSection title={dictionary.inspector.latestAuditEvents} action={dictionary.common.viewAll} onAction={() => setNotice(dictionary.inspector.auditOpened)}>
        <Timeline rows={[dictionary.inspector.timeline.strengthRecalculated, dictionary.inspector.timeline.sourceLinked, dictionary.inspector.timeline.evidenceUpdated]} compact />
      </InspectorSection>
      <div className="action-grid">
        <Button primary icon={Check} label={dictionary.actions.confirm} onClick={() => setNotice(dictionary.inspector.memoryConfirmed)} />
        <Button icon={Edit3} label={dictionary.actions.edit} onClick={() => setNotice(dictionary.inspector.editOpened)} />
        <Button icon={Pin} label={pinned ? dictionary.actions.pinned : dictionary.actions.pin} onClick={() => {
          setPinned((value) => !value);
          setNotice(pinned ? dictionary.inspector.pinRemoved : dictionary.inspector.memoryPinned);
        }} />
        <Button icon={Archive} label={dictionary.actions.archive} onClick={() => setNotice(dictionary.inspector.archiveRequested)} />
        <Button icon={EyeOff} label={dictionary.actions.hide} onClick={() => setNotice(dictionary.inspector.hiddenFromRecall)} />
        <Button icon={Eye} label={dictionary.actions.viewSource} onClick={onOpenDetail} />
      </div>
    </div>
  );
}
