import { Database, Eye, ShieldCheck } from "lucide-react";
import { Button, StatusPill } from "../../shared/components/ui";
import type { ControlPageDto } from "../../api/generated/controlPlane";

export function ProjectSourcePanel({
  page,
  selectedSource,
  onSelect,
  onOpen,
}: {
  page: ControlPageDto;
  selectedSource: string;
  onSelect: (source: string) => void;
  onOpen: () => void;
}) {
  const sourceIds = page.source_event_ids.length > 0 ? page.source_event_ids : ["none"];
  const selected = sourceIds.includes(selectedSource) ? selectedSource : sourceIds[0];
  const linkedTopics = page.topics.filter((topic) => topic.source_event_ids.includes(selected));

  return (
    <div className="project-split-panel">
      <div className="source-list">
        {sourceIds.map((sourceId) => (
          <button key={sourceId} className={sourceId === selected ? "is-selected" : ""} type="button" onClick={() => onSelect(sourceId)}>
            <span>{sourceId}</span>
            <strong>{linkedTopics.length} topics</strong>
            <StatusPill label={sourceId === "none" ? "Missing" : "Linked"} tone={sourceId === "none" ? "orange" : "green"} />
          </button>
        ))}
      </div>
      <article className="source-detail">
        <div className="doc-section-title">
          <Database size={20} />
          <h2>{selected}</h2>
          <StatusPill label="Source Event" tone="green" />
        </div>
        <div className="definition-columns">
          <dl className="definition"><dt>Project Space</dt><dd>{page.project_memory_space_id}</dd></dl>
          <dl className="definition"><dt>Scope</dt><dd>{page.scope_type}</dd></dl>
          <dl className="definition"><dt>Linked Topics</dt><dd>{linkedTopics.length}</dd></dl>
          <dl className="definition"><dt>Graph Raw</dt><dd>{page.graph_backend_raw_retained ? "retained" : "not retained"}</dd></dl>
        </div>
        {linkedTopics.map((topic) => <blockquote key={topic.title}>{topic.title}: {topic.summary}</blockquote>)}
        <div className="inline-action-row">
          <Button icon={Eye} label="Open Evidence" onClick={onOpen} disabled={selected === "none"} />
          <Button icon={ShieldCheck} label="Mark Reviewed" onClick={onOpen} disabled={selected === "none"} />
        </div>
      </article>
    </div>
  );
}
