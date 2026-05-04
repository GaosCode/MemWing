import { Link2, Network } from "lucide-react";
import { StatusPill } from "../../shared/components/ui";
import type { ControlPageDetailDto, ControlPageDto } from "../../api/generated/controlPlane";
import type { MemoryItem } from "../../shared/types/entities";

export function ProjectAuditPanel({
  detail,
  activeFilter,
  onFilter,
}: {
  detail: ControlPageDetailDto | null;
  activeFilter: string;
  onFilter: (filter: string) => void;
}) {
  const filters = ["All", "Page", "Version", "Source"];
  const auditRefs = detail?.audit_refs ?? [];
  const visibleRefs = activeFilter === "All" ? auditRefs : auditRefs.filter((ref) => ref.toLowerCase().includes(activeFilter.toLowerCase()));

  return (
    <div className="project-tab-panel">
      <div className="section-toolbar section-toolbar--flush">
        <h2>Audit Events</h2>
        <div className="chip-row">
          {filters.map((filter) => <button key={filter} className={filter === activeFilter ? "is-active" : ""} type="button" onClick={() => onFilter(filter)}>{filter}</button>)}
        </div>
      </div>
      <div className="audit-list">
        {visibleRefs.map((auditRef) => (
          <section key={auditRef} className="audit-row">
            <span>audit_events</span>
            <StatusPill label="Recorded" tone="green" />
            <strong>{auditRef}</strong>
            <span>backend</span>
          </section>
        ))}
        {visibleRefs.length === 0 ? <p>No audit refs matched this filter.</p> : null}
      </div>
    </div>
  );
}

export function ProjectGraphPanel({
  page,
  linkedMemories,
  onOpenTab,
}: {
  page: ControlPageDto;
  linkedMemories: MemoryItem[];
  onOpenTab: (tab: string, message: string) => void;
}) {
  const graphNodes = [
    { label: page.title, meta: `v${page.version}`, target: "Versions", message: "Page Memory version context opened" },
    { label: "Linked Memories", meta: `${linkedMemories.length} loaded`, target: "Document", message: "Linked memory section opened" },
    { label: "Source Events", meta: `${page.source_event_ids.length} events`, target: "Sources", message: "Source event evidence opened" },
    { label: "Topics", meta: `${page.topics.length} topics`, target: "Document", message: "Topic section opened from graph" },
    { label: "Rebuild State", meta: page.needs_rebuild ? "needs rebuild" : "current", target: "Rebuild Preview", message: "Rebuild state opened from graph" },
  ];
  const graphRelations = [
    ["Source Events", "support", page.title, `${page.source_event_ids.length} linked`],
    ["Linked Memories", "anchor", "Topics", `${page.linked_memory_item_ids.length} ids`],
    ["Topics", "summarize", page.title, `${page.topics.length} current`],
    ["Rebuild State", "guards", page.title, page.needs_rebuild ? "pending" : "current"],
  ];

  return (
    <div className="project-tab-panel">
      <div className="project-graph">
        {graphNodes.map((node, index) => (
          <button key={node.label} type="button" className={`graph-node graph-node--${index}`} onClick={() => onOpenTab(node.target, node.message)}>
            <Network size={18} />
            <strong>{node.label}</strong>
            <span>{node.meta}</span>
          </button>
        ))}
      </div>
      <div className="graph-relation-list">
        <div className="graph-relation-row graph-relation-row--head">
          <span>From</span>
          <span>Relation</span>
          <span>To</span>
          <span>State</span>
        </div>
        {graphRelations.map(([from, relation, to, state]) => (
          <button key={`${from}-${relation}-${to}`} className="graph-relation-row" type="button" onClick={() => onOpenTab(relation === "support" ? "Sources" : "Document", `${from} relation selected`)}>
            <strong>{from}</strong>
            <span>{relation}</span>
            <span>{to}</span>
            <StatusPill label={state} tone={state === "pending" ? "orange" : "green"} />
          </button>
        ))}
      </div>
      <div className="project-preview-note">
        <Link2 size={18} />
        <span>Graph is projected from Page Memory source links, linked memory ids, topics, and rebuild state returned by the backend.</span>
      </div>
    </div>
  );
}
