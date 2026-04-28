import { User } from "lucide-react";
import { Definition, InspectorHeader, InspectorSection, StrengthMeter, Timeline } from "../../shared/components/ui";

export function ProjectInspector({
  onOpenDetail,
  onClose,
  onNarrow,
  onWiden,
}: {
  onOpenDetail: () => void;
  onClose?: () => void;
  onNarrow?: () => void;
  onWiden?: () => void;
}) {
  return (
    <div className="inspector-panel">
      <InspectorHeader title="Project Inspector" onOpen={onOpenDetail} onClose={onClose} onNarrow={onNarrow} onWiden={onWiden} />
      <InspectorSection title="Project Status">
        <Definition label="Strength"><StrengthMeter value={0.84} /></Definition>
        <Definition label="Lifecycle">Active · Review Pending <span className="status-dot status-dot--orange" /></Definition>
        <Definition label="Last Rebuild">2026-04-27 11:32</Definition>
        <Definition label="Version">v3 current</Definition>
      </InspectorSection>
      <InspectorSection title="Version History" action="View all">
        <Timeline rows={["v3 current · 2026-04-27 11:32", "v2 · 2026-04-27 11:05", "v1 · 2026-04-27 10:15"]} compact />
      </InspectorSection>
      <InspectorSection title="Sources Used (24)" action="View all">
        <Definition label="Feishu · 产品群">14</Definition>
        <Definition label="Feishu · 安全群">5</Definition>
        <Definition label="AI 产品自动化维护">3</Definition>
        <Definition label="Others">2</Definition>
      </InspectorSection>
      <InspectorSection title="Captured / Updated">
        <div className="capture-user"><span className="avatar"><User size={16} /></span><strong>swift.gao</strong></div>
        <p>Last Updated: 2026-04-27 11:32:18</p>
      </InspectorSection>
    </div>
  );
}
