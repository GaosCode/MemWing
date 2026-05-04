import { CircleAlert, CircleCheck, Clock3, FileText, GitBranch, Link2, List } from "lucide-react";
import { Button, DocSection, StatusPill } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
import type { MemoryItem } from "../../shared/types/entities";
import type { ControlPageDto } from "../../api/generated/controlPlane";

export function ProjectDocument({
  page,
  linkedMemories,
  editingBrief,
  draftBrief,
  onDraftBrief,
  onToggleBrief,
  onSaveBrief,
  onOpenVersions,
  onOpenMemory,
}: {
  page: ControlPageDto;
  linkedMemories: MemoryItem[];
  editingBrief: boolean;
  draftBrief: string;
  onDraftBrief: (value: string) => void;
  onToggleBrief: () => void;
  onSaveBrief: () => void;
  onOpenVersions: () => void;
  onOpenMemory: (memory: MemoryItem) => void;
}) {
  const { dictionary } = useI18n();

  return (
    <article className="document-workbench">
      <DocSection icon={FileText} index="1" title={page.title}>
        {editingBrief ? (
          <textarea className="project-brief-editor" value={draftBrief} onChange={(event) => onDraftBrief(event.target.value)} />
        ) : (
          <p>{page.brief}</p>
        )}
        <div className="doc-section-actions">
          <Button icon={FileText} label={editingBrief ? "Close Draft" : "Edit Brief"} onClick={onToggleBrief} />
          {editingBrief ? <Button primary icon={CircleCheck} label="Save Brief" onClick={onSaveBrief} /> : null}
        </div>
      </DocSection>

      <DocSection icon={GitBranch} index="2" title="Scope" tag={`${page.scope_type} · ${page.scope_id}`}>
        <p>{page.project_memory_space_id}</p>
        <div className="definition-columns">
          <dl className="definition"><dt>Group</dt><dd>{page.group_id ?? "none"}</dd></dl>
          <dl className="definition"><dt>Thread</dt><dd>{page.thread_id ?? "none"}</dd></dl>
          <dl className="definition"><dt>Shared Group</dt><dd>{page.shared_group_id ?? "none"}</dd></dl>
          <dl className="definition"><dt>Updated</dt><dd>{page.updated_at}</dd></dl>
        </div>
      </DocSection>

      <DocSection icon={CircleCheck} index="3" title="Topics">
        {page.topics.length === 0 ? <p>No topics are linked to this Page Memory yet.</p> : null}
        <ul>
          {page.topics.map((topic) => (
            <li key={`${topic.title}-${topic.summary}`}>
              <strong>{topic.title}</strong>
              <span>{topic.summary}</span>
              <StatusPill label={`${topic.source_event_ids.length} sources`} tone={topic.source_event_ids.length > 0 ? "green" : "orange"} />
            </li>
          ))}
        </ul>
      </DocSection>

      <DocSection icon={CircleAlert} index="4" title="Open Questions">
        {page.open_questions.length === 0 ? <p>No open questions are currently tracked.</p> : null}
        <ul className="two-column-list">
          {page.open_questions.map((question) => (
            <li key={question}>{question}<StatusPill label={dictionary.status.maintenanceState.Open} tone="orange" /></li>
          ))}
        </ul>
      </DocSection>

      <DocSection icon={List} index="5" title="Next Steps">
        {page.next_steps.length === 0 ? <p>No next steps are currently tracked.</p> : null}
        <ol className="two-column-list">
          {page.next_steps.map((step) => (
            <li key={step}>{step}<StatusPill label={dictionary.status.maintenanceState.Open} tone="green" /></li>
          ))}
        </ol>
      </DocSection>

      <DocSection icon={Link2} index="6" title="Linked Memories">
        <div className="linked-memory-grid">
          {linkedMemories.map((memory) => (
            <button key={memory.id} className="linked-memory-card" type="button" onClick={() => onOpenMemory(memory)}>
              <FileText size={20} />
              <span>{memory.title}</span>
              <small>{memory.source} · {memory.lastSeen}</small>
              <StatusPill label={dictionary.status.lifecycle[memory.status].label} tone="green" />
            </button>
          ))}
          {linkedMemories.length === 0 ? <p>No linked memory item is currently loaded for this page.</p> : null}
        </div>
      </DocSection>

      <DocSection icon={Clock3} index="7" title="Recent Source Events">
        {page.source_event_ids.length === 0 ? <p>No source events are linked.</p> : null}
        {page.source_event_ids.slice(0, 6).map((sourceEventId) => (
          <p key={sourceEventId}>source_events · {sourceEventId}</p>
        ))}
        {page.source_event_ids.length > 6 ? <button type="button" onClick={onOpenVersions}>open all source-backed versions</button> : null}
      </DocSection>
    </article>
  );
}
