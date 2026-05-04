import { useState } from "react";
import { Eye, FileText, RotateCcw, ShieldCheck, X } from "lucide-react";
import { Button, Definition, InspectorHeader, InspectorSection, StatusPill } from "../../shared/components/ui";
import { severityTone } from "../../shared/design-system/status";
import { maintenanceStateLabel, severityLabel } from "../../shared/i18n/formatters";
import { useI18n } from "../../shared/i18n";
import type { MaintenanceItem } from "../../shared/types/entities";
import { linkedReferences } from "./maintenanceData";
import type { MaintenanceAction } from "./MaintenanceQueues";

export function MaintenanceInspector({
  item,
  onOpenDetail,
  onAction,
  onClose,
}: {
  item: MaintenanceItem;
  onOpenDetail: () => void;
  onAction: (item: MaintenanceItem, action: MaintenanceAction) => Promise<void>;
  onClose?: () => void;
}) {
  const { dictionary } = useI18n();
  const [notice, setNotice] = useState(dictionary.maintenance.reviewBeforeRetry);
  const [pinned, setPinned] = useState(false);
  const statusTone = item.state === "Failed" ? "red" : item.state === "Open" ? "green" : "orange";

  function runPrimaryAction() {
    const action: MaintenanceAction = item.actionKind === "push_candidate" ? "approve" : "retry";
    setNotice("Sending maintenance action to backend");
    void onAction(item, action)
      .then(() => setNotice("Backend maintenance action completed"))
      .catch((error) => setNotice(error instanceof Error ? error.message : "MemWing API request failed"));
  }

  return (
    <div className="inspector-panel">
      <InspectorHeader title={dictionary.maintenance.inspectorTitle} onOpen={onOpenDetail} onClose={onClose} pinned={pinned} onPin={() => {
        setPinned((value) => !value);
        setNotice(pinned ? dictionary.maintenance.inspectorUnpinned : dictionary.maintenance.inspectorPinned);
      }} />
      <h2>{item.title}</h2>
      <div className="inspector-notice">{notice}</div>
      <div className="definition-grid definition-grid--maintenance">
        <Definition label={dictionary.maintenance.metrics.status}><StatusPill label={maintenanceStateLabel(dictionary, item.state)} tone={statusTone} /></Definition>
        <Definition label={dictionary.maintenance.metrics.severity}><StatusPill label={severityLabel(dictionary, item.severity)} tone={severityTone[item.severity]} /></Definition>
        <Definition label={dictionary.maintenance.metrics.retryCount}>{item.state === "Failed" ? "2" : "0"}</Definition>
        <Definition label={dictionary.maintenance.metrics.affectedMemories}>{item.state === "Failed" ? "3" : "1"}</Definition>
      </div>
      <InspectorSection title={dictionary.maintenance.reason}>
        <p>{item.reason}. {item.state === "Failed" ? "Candidate touched an active project section with unresolved contradictions." : "Reviewer action is required before automation continues."}</p>
      </InspectorSection>
      <InspectorSection title={dictionary.maintenance.recommendedAction}>
        <p>{item.state === "Failed" ? "Review linked evidence before retrying. Retry is safe after conflict state is resolved." : "Open the full detail, inspect evidence, then confirm or dismiss this maintenance task."}</p>
      </InspectorSection>
      <InspectorSection title={dictionary.maintenance.linkedReferences}>
        <div className="reference-grid">
          {linkedReferences.map((ref) => (
            <button key={ref.label} type="button" onClick={() => setNotice(`${ref.label} opened`)}><FileText size={17} />{ref.label}</button>
          ))}
        </div>
      </InspectorSection>
      <div className="action-grid">
        <Button primary icon={RotateCcw} label={item.actionKind === "push_candidate" ? "Approve Push" : item.state === "Failed" ? dictionary.actions.retryJob : dictionary.actions.rerunCheck} onClick={runPrimaryAction} disabled={item.actionKind === "job" && !item.retryable} />
        <Button icon={ShieldCheck} label={dictionary.actions.openAudit} onClick={onOpenDetail} />
        <Button icon={Eye} label={dictionary.actions.viewSource} onClick={() => setNotice(dictionary.maintenance.sourcePreviewOpened)} />
        <Button icon={X} label={dictionary.actions.dismiss} onClick={onClose} />
      </div>
    </div>
  );
}
