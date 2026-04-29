import { useState } from "react";
import { Eye, FileText, RotateCcw, ShieldCheck, X } from "lucide-react";
import { Button, Definition, InspectorHeader, InspectorSection, StatusPill } from "../../shared/components/ui";
import type { MaintenanceItem } from "../../shared/types/entities";

export function MaintenanceInspector({
  item,
  onOpenDetail,
  onClose,
}: {
  item: MaintenanceItem;
  onOpenDetail: () => void;
  onClose?: () => void;
}) {
  const [notice, setNotice] = useState("Review linked evidence before retry");
  const [pinned, setPinned] = useState(false);

  return (
    <div className="inspector-panel">
      <InspectorHeader title="Maintenance Inspector" onOpen={onOpenDetail} onClose={onClose} pinned={pinned} onPin={() => {
        setPinned((value) => !value);
        setNotice(pinned ? "Inspector unpinned" : "Inspector pinned");
      }} />
      <h2>{item.title} into Project Memory</h2>
      <div className="inspector-notice">{notice}</div>
      <div className="definition-grid definition-grid--maintenance">
        <Definition label="Status"><StatusPill label={item.state} tone={item.state === "Failed" ? "red" : "orange"} /></Definition>
        <Definition label="Severity">High</Definition>
        <Definition label="Retry Count">2</Definition>
        <Definition label="Affected Memories">3</Definition>
      </div>
      <InspectorSection title="Reason">
        <p>Conflict threshold exceeded during promotion. Candidate touched an active project section with unresolved contradictions.</p>
      </InspectorSection>
      <InspectorSection title="Recommended Action">
        <p>Review linked evidence before retrying. Retry is safe after conflict state is resolved.</p>
      </InspectorSection>
      <InspectorSection title="Linked References">
        <div className="reference-grid">
          {["source_events", "memory_items", "memory_pages", "audit_events"].map((ref) => (
            <button key={ref} type="button" onClick={() => setNotice(`${ref} opened`)}><FileText size={17} />{ref}</button>
          ))}
        </div>
      </InspectorSection>
      <div className="action-grid">
        <Button primary icon={RotateCcw} label="Retry Job" onClick={() => setNotice("Retry queued after manual review")} />
        <Button icon={ShieldCheck} label="Open Audit" onClick={onOpenDetail} />
        <Button icon={Eye} label="View Source" onClick={() => setNotice("Source preview opened")} />
        <Button icon={X} label="Dismiss" onClick={onClose} />
      </div>
    </div>
  );
}
