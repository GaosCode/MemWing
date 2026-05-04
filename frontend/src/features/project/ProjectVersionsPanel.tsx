import { GitCompare, History, RefreshCcw } from "lucide-react";
import { Button, StatusPill } from "../../shared/components/ui";
import type { ControlPageDetailDto, ControlPageDto, ControlPageVersionDto } from "../../api/generated/controlPlane";

export function ProjectVersionsPanel({
  page,
  detail,
  selectedVersion,
  updating,
  onSelect,
  onRestore,
}: {
  page: ControlPageDto;
  detail: ControlPageDetailDto | null;
  selectedVersion: number;
  updating: boolean;
  onSelect: (version: number) => void;
  onRestore: (version: number) => void;
}) {
  const versions = detail?.versions ?? [];
  const version = versions.find((item) => item.version === selectedVersion) ?? versions[0] ?? currentPageVersion(page);

  return (
    <div className="project-split-panel">
      <div className="source-list">
        {[currentPageVersion(page), ...versions.filter((item) => item.version !== page.version)].map((item) => (
          <button key={`${item.id}-${item.version}`} className={item.version === version.version ? "is-selected" : ""} type="button" onClick={() => onSelect(item.version)}>
            <span>v{item.version} · {item.changed_by}</span>
            <strong>{item.created_at}</strong>
            <StatusPill label={item.version === page.version ? "Current" : "Restorable"} tone={item.version === page.version ? "green" : "gray"} />
          </button>
        ))}
      </div>
      <article className="source-detail">
        <div className="doc-section-title">
          <History size={20} />
          <h2>v{version.version} · {version.title}</h2>
          <StatusPill label={version.version === page.version ? "Current" : "Restorable"} tone={version.version === page.version ? "green" : "gray"} />
        </div>
        <div className="version-diff">
          <div><span>Brief</span><p>{version.brief}</p></div>
          <div><span>Topics</span><p>{version.topics.length} linked topics</p></div>
          <div><span>Reason</span><p>{version.change_reason}</p></div>
        </div>
        <div className="inline-action-row">
          <Button icon={GitCompare} label="Compare" onClick={() => onSelect(version.version)} />
          <Button icon={RefreshCcw} label={updating ? "Restoring" : "Restore Version"} onClick={() => onRestore(version.version)} disabled={version.version === page.version || updating} />
        </div>
      </article>
    </div>
  );
}

function currentPageVersion(page: ControlPageDto): ControlPageVersionDto {
  return {
    id: page.id,
    page_id: page.id,
    version: page.version,
    title: page.title,
    brief: page.brief,
    topics: page.topics,
    open_questions: page.open_questions,
    next_steps: page.next_steps,
    source_event_ids: page.source_event_ids,
    linked_memory_item_ids: page.linked_memory_item_ids,
    changed_by: "current",
    change_reason: "Current backend projection",
    created_at: page.updated_at,
  };
}
