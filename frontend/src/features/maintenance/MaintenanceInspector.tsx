import { useState } from "react";
import { Eye, FileText, RotateCcw, ShieldCheck, X } from "lucide-react";
import { Button, Definition, InspectorHeader, InspectorSection, StatusPill } from "../../shared/components/ui";
import { severityStatus } from "../../shared/design-system/status";
import type { MaintenanceItem } from "../../shared/types/entities";
import { linkedReferences } from "./maintenanceData";

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
  const severityMeta = severityStatus[item.severity];
  const statusTone = item.state === "Failed" ? "red" : item.state === "Open" ? "green" : "orange";

  return (
    <div className="inspector-panel">
      <InspectorHeader title="Maintenance Inspector" onOpen={onOpenDetail} onClose={onClose} pinned={pinned} onPin={() => {
        setPinned((value) => !value);
        setNotice(pinned ? "Inspector unpinned" : "Inspector pinned");
      }} />
      <h2>{item.title}</h2>
      <div className="inspector-notice">{notice}</div>
      <div className="definition-grid definition-grid--maintenance">
        <Definition label="Status"><StatusPill label={item.state} tone={statusTone} /></Definition>
        <Definition label="Severity">{severityMeta.label}</Definition>
        <Definition label="Retry Count">{item.state === "Failed" ? "2" : "0"}</Definition>
        <Definition label="Affected Memories">{item.state === "Failed" ? "3" : "1"}</Definition>
      </div>
      <InspectorSection title="Reason">
        <p>{item.reason}. {item.state === "Failed" ? "Candidate touched an active project section with unresolved contradictions." : "Reviewer action is required before automation continues."}</p>
      </InspectorSection>
      <InspectorSection title="Recommended Action">
        <p>{item.state === "Failed" ? "Review linked evidence before retrying. Retry is safe after conflict state is resolved." : "Open the full detail, inspect evidence, then confirm or dismiss this maintenance task."}</p>
      </InspectorSection>
      <InspectorSection title="Linked References">
        <div className="reference-grid">
          {linkedReferences.map((ref) => (
            <button key={ref.label} type="button" onClick={() => setNotice(`${ref.label} opened`)}><FileText size={17} />{ref.label}</button>
          ))}
        </div>
      </InspectorSection>
      <div className="action-grid">
        <Button primary icon={RotateCcw} label={item.state === "Failed" ? "Retry Job" : "Re-run Check"} onClick={() => setNotice(item.state === "Failed" ? "Retry queued after manual review" : "Maintenance check queued")} />
        <Button icon={ShieldCheck} label="Open Audit" onClick={onOpenDetail} />
        <Button icon={Eye} label="View Source" onClick={() => setNotice("Source preview opened")} />
        <Button icon={X} label="Dismiss" onClick={onClose} />
      </div>
    </div>
  );
}
