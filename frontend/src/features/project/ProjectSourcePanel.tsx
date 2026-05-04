import { Check, Clipboard, Database, Eye } from "lucide-react";
import { useState } from "react";
import { Button, StatusPill } from "../../shared/components/ui";
import type { ControlPageDto, ControlSourceEventDetailDto } from "../../api/generated/controlPlane";

export function ProjectSourcePanel({
  page,
  selectedSource,
  sourceDetail,
  loading,
  onSelect,
  onOpen,
}: {
  page: ControlPageDto;
  selectedSource: string;
  sourceDetail: ControlSourceEventDetailDto | null;
  loading: boolean;
  onSelect: (source: string) => void;
  onOpen: (source: string) => void;
}) {
  const [copyState, setCopyState] = useState("Ready");
  const sourceIds = page.source_event_ids.length > 0 ? page.source_event_ids : ["none"];
  const selected = sourceIds.includes(selectedSource) ? selectedSource : sourceIds[0];
  const linkedTopics = page.topics.filter((topic) => topic.source_event_ids.includes(selected));
  const detail = sourceDetail?.source_event.id === selected ? sourceDetail : null;

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
        {detail !== null ? (
          <div className="definition-columns">
            <dl className="definition"><dt>Preview</dt><dd>{detail.source_event.content_preview}</dd></dl>
            <dl className="definition"><dt>Event Time</dt><dd>{detail.source_event.event_time}</dd></dl>
            <dl className="definition"><dt>Linked Memories</dt><dd>{detail.memory_item_ids.length}</dd></dl>
            <dl className="definition"><dt>Audit Refs</dt><dd>{detail.audit_refs.length}</dd></dl>
            <dl className="definition"><dt>Source URL</dt><dd>{detail.source_event.source_url ?? "none"}</dd></dl>
            <dl className="definition"><dt>Purge State</dt><dd>{detail.source_event.purged ? detail.source_event.purge_level : "available"}</dd></dl>
          </div>
        ) : null}
        {linkedTopics.map((topic) => <blockquote key={topic.title}>{topic.title}: {topic.summary}</blockquote>)}
        <div className="inline-action-row">
          <Button icon={Eye} label={loading ? "Loading Evidence" : "Open Evidence"} onClick={() => onOpen(selected)} disabled={selected === "none" || loading} />
          <Button icon={Clipboard} label="Copy Source ID" onClick={() => void copySourceId(selected)} disabled={selected === "none"} />
        </div>
        <div className="notice-row"><Check size={15} />{copyState}</div>
      </article>
    </div>
  );

  async function copySourceId(sourceId: string) {
    try {
      await navigator.clipboard.writeText(sourceId);
      setCopyState(`Copied ${sourceId}`);
    } catch {
      setCopyState(sourceId);
    }
  }
}
