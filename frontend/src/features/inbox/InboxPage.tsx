import { useState } from "react";
import { ChevronDown, CircleAlert, FileText, List, ListFilter, MoreHorizontal, ShieldCheck, type LucideIcon } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { IconButton, PageHeader, StatusBadge } from "../../shared/components/ui";
import type { MemoryItem } from "../../shared/types/entities";

export function InboxPage({ selected, onSelect }: { selected: MemoryItem; onSelect: (memory: MemoryItem) => void }) {
  const [compact, setCompact] = useState(false);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [expandedQueues, setExpandedQueues] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState("Review queue ready");
  const reviewMemories = reviewOnly ? memories.slice(0, 2) : memories.slice(0, 2);

  function toggleQueue(title: string) {
    setExpandedQueues((current) => ({ ...current, [title]: !current[title] }));
  }

  return (
    <>
      <PageHeader
        title="收件箱审阅队列"
        subtitle="对 AI 捕获的记忆执行人工治理"
        actions={
          <>
            <span className="muted-count">共 13 项</span>
            <IconButton label="筛选" icon={ListFilter} onClick={() => {
              setReviewOnly((value) => !value);
              setNotice(reviewOnly ? "Showing all review lanes" : "Showing items that need review");
            }} />
            <IconButton label="列表密度" icon={List} onClick={() => {
              setCompact((value) => !value);
              setNotice(compact ? "Comfortable queue density" : "Compact queue density");
            }} />
          </>
        }
      />

      <div className="notice-row"><ShieldCheck size={15} />{notice}</div>

      {!reviewOnly ? (
        <div className={`queue-section ${compact ? "queue-section--compact" : ""}`}>
          <SectionHeading icon={ShieldCheck} title="候选记忆" count="3" />
          {memories.slice(2, 5).map((memory) => (
            <QueueRow key={memory.id} memory={memory} selected={selected.id === memory.id} onSelect={onSelect} compact />
          ))}
        </div>
      ) : null}

      <div className={`queue-section ${compact ? "queue-section--compact" : ""}`}>
        <SectionHeading icon={CircleAlert} title="需审阅" count="2" warning />
        {reviewMemories.map((memory) => (
          <QueueRow key={memory.id} memory={memory} selected={selected.id === memory.id} onSelect={onSelect} />
        ))}
      </div>

      <CollapsedQueue title="即将过期" count="2" tone="warning" right="2 天后" expanded={!!expandedQueues["即将过期"]} onToggle={() => toggleQueue("即将过期")} onSelect={onSelect} />
      <CollapsedQueue title="待推送" count="2" tone="success" right="4 项" expanded={!!expandedQueues["待推送"]} onToggle={() => toggleQueue("待推送")} onSelect={onSelect} />
      <CollapsedQueue title="冲突" count="2" tone="danger" right="3 高" expanded={!!expandedQueues["冲突"]} onToggle={() => toggleQueue("冲突")} onSelect={onSelect} />
      <CollapsedQueue title="已脱敏来源" count="2" tone="danger" right="2 项" expanded={!!expandedQueues["已脱敏来源"]} onToggle={() => toggleQueue("已脱敏来源")} onSelect={onSelect} />
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
  count,
  tone,
  right,
  expanded,
  onToggle,
  onSelect,
}: {
  title: string;
  count: string;
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
        <span className="pill-count">{count}</span>
        <span className={`queue-right queue-right--${tone}`}>{right}</span>
        <ChevronDown size={18} />
      </button>
      {expanded ? (
        <div className="queue-section queue-section--nested">
          {memories.slice(0, 2).map((memory) => (
            <QueueRow key={`${title}-${memory.id}`} memory={memory} selected={false} onSelect={onSelect} compact />
          ))}
        </div>
      ) : null}
    </section>
  );
}
