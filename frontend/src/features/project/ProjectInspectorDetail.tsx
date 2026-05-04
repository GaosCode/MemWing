import { ArrowLeft } from "lucide-react";
import type { PageEditInput } from "../../shared/api/controlPlaneClient";
import type { MemoryItem } from "../../shared/types/entities";
import type { ControlPageDetailDto, ControlPageDto } from "../../api/generated/controlPlane";
import { ProjectPage } from "./ProjectPage";

export function ProjectInspectorDetail({
  page,
  detail,
  memories,
  onSelectMemory,
  onRebuildPage,
  onEditPage,
  onRestorePageVersion,
  onBack,
}: {
  page: ControlPageDto;
  detail: ControlPageDetailDto | null;
  memories: MemoryItem[];
  onSelectMemory: (memory: MemoryItem) => void;
  onRebuildPage: (page: ControlPageDto) => Promise<void>;
  onEditPage: (page: ControlPageDto, input: PageEditInput, reason: string) => Promise<void>;
  onRestorePageVersion: (page: ControlPageDto, version: number) => Promise<void>;
  onBack: () => void;
}) {
  return (
    <section className="detail-page">
      <header className="detail-header">
        <div>
          <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to Project</button>
          <h1>Project Inspector</h1>
          <p>Review Page Memory, source links, versions, audit refs, and graph projection from the backend.</p>
        </div>
      </header>
      <ProjectPage
        page={page}
        detail={detail}
        memories={memories}
        onSelectMemory={onSelectMemory}
        onRebuildPage={onRebuildPage}
        onEditPage={onEditPage}
        onRestorePageVersion={onRestorePageVersion}
      />
    </section>
  );
}
