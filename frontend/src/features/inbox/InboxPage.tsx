import { useState } from "react";
import { ChevronDown, CircleAlert, FileText, List, ListFilter, MoreHorizontal, ShieldCheck, type LucideIcon } from "lucide-react";
import { IconButton, PageHeader, StatusBadge } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
import type { MemoryItem } from "../../shared/types/entities";

export function InboxPage({
  memories,
  selected,
  onSelect,
}: {
  memories: MemoryItem[];
  selected: MemoryItem;
  onSelect: (memory: MemoryItem) => void;
}) {
  const { dictionary } = useI18n();
  const [compact, setCompact] = useState(false);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [expandedQueues, setExpandedQueues] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState(dictionary.inbox.noticeReady);
  const reviewMemories = memories.filter((memory) => (
    memory.status === "candidate" ||
    memory.status === "needs_review" ||
    memory.forgetting.curveState === "below_threshold"
  ));
  const candidateMemories = memories.filter((memory) => memory.status === "candidate");

  function toggleQueue(title: string) {
    setExpandedQueues((current) => ({ ...current, [title]: !current[title] }));
  }

  return (
    <>
      <PageHeader
        title={dictionary.inbox.title}
        subtitle={dictionary.inbox.subtitle}
        actions={
          <>
            <span className="muted-count">{dictionary.inbox.totalCount}</span>
            <IconButton label={dictionary.inbox.filter} icon={ListFilter} onClick={() => {
              setReviewOnly((value) => !value);
              setNotice(reviewOnly ? dictionary.inbox.noticeAll : dictionary.inbox.noticeReviewOnly);
            }} />
            <IconButton label={dictionary.inbox.density} icon={List} onClick={() => {
              setCompact((value) => !value);
              setNotice(compact ? dictionary.inbox.noticeComfortable : dictionary.inbox.noticeCompact);
            }} />
          </>
        }
      />

      <div className="notice-row"><ShieldCheck size={15} />{notice}</div>

      {!reviewOnly ? (
        <div className={`queue-section ${compact ? "queue-section--compact" : ""}`}>
          <SectionHeading icon={ShieldCheck} title={dictionary.inbox.candidateMemories} count={String(candidateMemories.length)} />
          {candidateMemories.map((memory) => (
            <QueueRow key={memory.id} memory={memory} selected={selected.id === memory.id} onSelect={onSelect} compact />
          ))}
        </div>
      ) : null}

      <div className={`queue-section ${compact ? "queue-section--compact" : ""}`}>
        <SectionHeading icon={CircleAlert} title={dictionary.inbox.needsReview} count={String(reviewMemories.length)} warning />
        {(reviewOnly ? reviewMemories : reviewMemories.slice(0, 8)).map((memory) => (
          <QueueRow key={memory.id} memory={memory} selected={selected.id === memory.id} onSelect={onSelect} />
        ))}
      </div>

      <CollapsedQueue title={dictionary.inbox.queues.expiringSoon} memories={memories.filter((memory) => memory.forgetting.curveState === "fading")} tone="warning" right="review" expanded={!!expandedQueues.expiringSoon} onToggle={() => toggleQueue("expiringSoon")} onSelect={onSelect} />
      <CollapsedQueue title={dictionary.inbox.queues.pendingPush} memories={[]} tone="success" right="0 项" expanded={!!expandedQueues.pendingPush} onToggle={() => toggleQueue("pendingPush")} onSelect={onSelect} />
      <CollapsedQueue title={dictionary.inbox.queues.conflicts} memories={memories.filter((memory) => memory.flags.includes("conflict"))} tone="danger" right="review" expanded={!!expandedQueues.conflicts} onToggle={() => toggleQueue("conflicts")} onSelect={onSelect} />
      <CollapsedQueue title={dictionary.inbox.queues.redactedSources} memories={memories.filter((memory) => memory.flags.includes("source_redacted"))} tone="danger" right="review" expanded={!!expandedQueues.redactedSources} onToggle={() => toggleQueue("redactedSources")} onSelect={onSelect} />
    </>
  );
}

function QueueRow({
  memory,
  selected,
  compact,
  onSelect,
}: {
  memory: MemoryItem;
  selected: boolean;
  compact?: boolean;
  onSelect: (memory: MemoryItem) => void;
}) {
  return (
    <button className={`queue-row ${selected ? "is-selected" : ""}`} onClick={() => onSelect(memory)}>
      <FileText size={20} />
      <span className="queue-title">{memory.title}</span>
      <span>{memory.source} · {compact ? "04-26" : "04-27"}</span>
      <StatusBadge status={compact ? "candidate" : memory.status} />
      <span className="metric-number">{memory.strength.toFixed(2)}</span>
      <MoreHorizontal size={18} />
    </button>
  );
}

function SectionHeading({
  icon: Icon,
  title,
  count,
  warning,
}: {
  icon: LucideIcon;
  title: string;
  count: string;
  warning?: boolean;
}) {
  return (
    <div className="section-heading">
      <Icon size={22} className={warning ? "icon-warning" : "icon-success"} />
      <h2>{title}</h2>
      <span className="pill-count">{count}</span>
    </div>
  );
}

function CollapsedQueue({
  title,
  memories,
  tone,
  right,
  expanded,
  onToggle,
  onSelect,
}: {
  title: string;
  memories: MemoryItem[];
  tone: "success" | "warning" | "danger";
  right: string;
  expanded: boolean;
  onToggle: () => void;
  onSelect: (memory: MemoryItem) => void;
}) {
  return (
    <section className="collapsed-queue-group">
      <button className="collapsed-queue" type="button" aria-expanded={expanded} onClick={onToggle}>
        <span className={`queue-symbol queue-symbol--${tone}`} />
        <span>{title}</span>
        <span className="pill-count">{memories.length}</span>
        <span className={`queue-right queue-right--${tone}`}>{right}</span>
        <ChevronDown size={18} />
      </button>
      {expanded ? (
        <div className="queue-section queue-section--nested">
          {memories.slice(0, 8).map((memory) => (
            <QueueRow key={`${title}-${memory.id}`} memory={memory} selected={false} onSelect={onSelect} compact />
          ))}
        </div>
      ) : null}
    </section>
  );
}
