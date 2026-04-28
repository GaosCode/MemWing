import { ChevronDown, CircleAlert, FileText, List, ListFilter, MoreHorizontal, ShieldCheck, type LucideIcon } from "lucide-react";
import { memories } from "../../shared/api/mockData";
import { IconButton, PageHeader, StatusBadge } from "../../shared/components/ui";
import type { MemoryItem } from "../../shared/types/entities";

export function InboxPage({ selected, onSelect }: { selected: MemoryItem; onSelect: (memory: MemoryItem) => void }) {
  return (
    <>
      <PageHeader
        title="收件箱审阅队列"
        subtitle="对 AI 捕获的记忆执行人工治理"
        actions={
          <>
            <span className="muted-count">共 13 项</span>
            <IconButton label="筛选" icon={ListFilter} />
            <IconButton label="列表密度" icon={List} />
          </>
        }
      />

      <div className="queue-section">
        <SectionHeading icon={ShieldCheck} title="候选记忆" count="3" />
        {memories.slice(2, 5).map((memory) => (
          <QueueRow key={memory.id} memory={memory} selected={selected.id === memory.id} onSelect={onSelect} compact />
        ))}
      </div>

      <div className="queue-section">
        <SectionHeading icon={CircleAlert} title="需审阅" count="2" warning />
        {memories.slice(0, 2).map((memory) => (
          <QueueRow key={memory.id} memory={memory} selected={selected.id === memory.id} onSelect={onSelect} />
        ))}
      </div>

      <CollapsedQueue title="即将过期" count="2" tone="warning" right="2 天后" />
      <CollapsedQueue title="待推送" count="2" tone="success" right="4 项" />
      <CollapsedQueue title="冲突" count="2" tone="danger" right="3 高" />
      <CollapsedQueue title="已脱敏来源" count="2" tone="danger" right="2 项" />
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
}: {
  title: string;
  count: string;
  tone: "success" | "warning" | "danger";
  right: string;
}) {
  return (
    <button className="collapsed-queue" type="button">
      <span className={`queue-symbol queue-symbol--${tone}`} />
      <span>{title}</span>
      <span className="pill-count">{count}</span>
      <span className={`queue-right queue-right--${tone}`}>{right}</span>
      <ChevronDown size={18} />
    </button>
  );
}
