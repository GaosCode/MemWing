import { useState } from "react";
import { User } from "lucide-react";
import { Definition, InspectorHeader, InspectorSection, StrengthMeter, Timeline } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
import type { ControlPageDetailDto, ControlPageDto } from "../../api/generated/controlPlane";

export function ProjectInspector({
  page,
  detail,
  onOpenDetail,
  onClose,
}: {
  page: ControlPageDto | null;
  detail: ControlPageDetailDto | null;
  onOpenDetail: () => void;
  onClose?: () => void;
}) {
  const { dictionary } = useI18n();
  const [notice, setNotice] = useState("Project inspector ready");
  const [pinned, setPinned] = useState(false);

  return (
    <div className="inspector-panel">
      <InspectorHeader title={dictionary.app.nav.project} onOpen={onOpenDetail} onClose={onClose} pinned={pinned} onPin={() => {
        setPinned((value) => !value);
        setNotice(pinned ? "Inspector unpinned" : "Inspector pinned");
      }} />
      <div className="inspector-notice">{notice}</div>
      <InspectorSection title="Project Status">
        <Definition label={dictionary.inspector.strength}><StrengthMeter value={page?.needs_rebuild ? 0.56 : 0.84} /></Definition>
        <Definition label="Lifecycle">{dictionary.status.lifecycle.active.label} · {page?.needs_rebuild ? dictionary.status.maintenanceState["Review Pending"] : dictionary.status.maintenanceState.Open} <span className={`status-dot ${page?.needs_rebuild ? "status-dot--orange" : "status-dot--green"}`} /></Definition>
        <Definition label="Last Rebuild">{page?.updated_at ?? "none"}</Definition>
        <Definition label="Version">{page ? `v${page.version} current` : "none"}</Definition>
      </InspectorSection>
      <InspectorSection title="Version History" action="View all" onAction={() => setNotice("Version history opened in full inspector")}>
        <Timeline rows={(detail?.versions ?? []).slice(0, 4).map((version) => `v${version.version} · ${version.created_at}`)} compact />
      </InspectorSection>
      <InspectorSection title={`Sources Used (${page?.source_event_ids.length ?? 0})`} action="View all" onAction={() => setNotice("Source coverage opened")}>
        {(page?.source_event_ids ?? []).slice(0, 4).map((sourceEventId) => (
          <Definition key={sourceEventId} label="source_event">{sourceEventId}</Definition>
        ))}
      </InspectorSection>
      <InspectorSection title="Captured / Updated">
        <div className="capture-user"><span className="avatar"><User size={16} /></span><strong>swift.gao</strong></div>
        <p>Last Updated: {page?.updated_at ?? "none"}</p>
      </InspectorSection>
    </div>
  );
}
