import { Clock3, FileText, TrendingDown } from "lucide-react";
import { Button, StatusPill, StrengthMeter } from "../../shared/components/ui";
import { curveStateLabel, maintenanceStateLabel } from "../../shared/i18n/formatters";
import { useI18n } from "../../shared/i18n";
import type { MemoryLifecycleAction } from "../../api/generated/controlPlane";
import type { MaintenanceItem, MemoryItem } from "../../shared/types/entities";
import { maintenanceItemKey } from "./MaintenanceQueues";

export function ForgettingReview({
  items,
  memories,
  onSelect,
  onRefresh,
  onDecision,
  onMemoryLifecycleAction,
  decisions,
}: {
  items: MaintenanceItem[];
  memories: MemoryItem[];
  onSelect: (item: MaintenanceItem) => void;
  onRefresh: () => void;
  onDecision: (key: string, decision: string) => void;
  onMemoryLifecycleAction: (memory: MemoryItem, action: MemoryLifecycleAction, reason: string) => Promise<void>;
  decisions: Record<string, string>;
}) {
  const { dictionary } = useI18n();
  const forgettingItems = items.filter((item) => item.type === "Forgetting" || item.state === "Ready to forget");
  const fadingMemories = memories.filter((memory) => memory.forgetting.curveState !== "retained").slice(0, 4);
  const decayPoints = fadingMemories[0]?.forgetting.curvePoints.length
    ? fadingMemories[0].forgetting.curvePoints.map((point) => ({ day: `D${point.day}`, score: point.score }))
    : [
        { day: "D0", score: 0.92 },
        { day: "D7", score: 0.78 },
        { day: "D14", score: 0.61 },
        { day: "D21", score: 0.48 },
        { day: "D30", score: 0.31 },
      ];
  const decayPolyline = decayPoints
    .map((point, index) => `${18 + index * 71},${18 + (1 - point.score) * 104}`)
    .join(" ");

  return (
    <>
      <div className="section-toolbar">
        <div>
          <h2>Forgetting Curve Review</h2>
          <p className="section-subtitle">Review decay score, next review, and retention reason before memory is forgotten.</p>
        </div>
        <Button icon={TrendingDown} label={dictionary.actions.refreshDecayScores} onClick={onRefresh} />
      </div>
      <div className="curve-review-grid">
        <section className="curve-panel">
          <h3>Decay thresholds</h3>
          <div className="curve-line" aria-hidden="true">
            <svg viewBox="0 0 320 150" role="img" aria-label="Decay score trend">
              <line className="curve-grid-line" x1="18" y1="75" x2="302" y2="75" />
              <line className="curve-threshold-line curve-threshold-line--recall" x1="18" y1="75.2" x2="302" y2="75.2" />
              <line className="curve-threshold-line curve-threshold-line--forget" x1="18" y1="88.7" x2="302" y2="88.7" />
              <polyline className="curve-trend-fill" points={`18,122 ${decayPolyline} 302,122`} />
              <polyline className="curve-trend-line" points={decayPolyline} />
              {decayPoints.map((point, index) => {
                const x = 18 + index * 71;
                const y = 18 + (1 - point.score) * 104;
                return (
                  <g key={point.day}>
                    <circle className="curve-point" cx={x} cy={y} r="4.5" />
                    <text className="curve-point-label" x={x} y={y - 10}>{point.score.toFixed(2)}</text>
                    <text className="curve-day-label" x={x} y="142">{point.day}</text>
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="curve-thresholds">
            <span>Recall threshold <strong>{(fadingMemories[0]?.forgetting.recallThreshold ?? 0.45).toFixed(2)}</strong></span>
            <span>Next review <strong>{fadingMemories[0]?.forgetting.nextReviewAt ?? "none"}</strong></span>
            <span>Backend candidates <strong>{forgettingItems.length}</strong></span>
          </div>
        </section>
        <section className="curve-panel">
          <h3>Review queue</h3>
          {fadingMemories.map((memory) => (
            <ForgettingMemoryRow
              key={memory.id}
              memory={memory}
              decision={decisions[memory.id]}
              onDecision={onDecision}
              onMemoryLifecycleAction={onMemoryLifecycleAction}
            />
          ))}
          {forgettingItems.map((item) => (
            <button key={item.id} className="curve-review-row curve-review-row--task" type="button" onClick={() => onSelect(item)}>
              <Clock3 size={17} />
              <span>{item.title}</span>
              <StrengthMeter value={0.48} compact />
              <StatusPill label={decisions[maintenanceItemKey(item)] ?? maintenanceStateLabel(dictionary, item.state)} tone="orange" />
            </button>
          ))}
          {fadingMemories.length === 0 && forgettingItems.length === 0 ? <p>No forgetting review candidate is currently visible for this scope.</p> : null}
        </section>
      </div>
    </>
  );
}

function ForgettingMemoryRow({
  memory,
  decision,
  onDecision,
  onMemoryLifecycleAction,
}: {
  memory: MemoryItem;
  decision?: string;
  onDecision: (key: string, decision: string) => void;
  onMemoryLifecycleAction: (memory: MemoryItem, action: MemoryLifecycleAction, reason: string) => Promise<void>;
}) {
  const { dictionary } = useI18n();
  function runAction(action: MemoryLifecycleAction, label: string) {
    onDecision(memory.id, "Sending to backend");
    void onMemoryLifecycleAction(memory, action, `forgetting review ${label}`)
      .then(() => onDecision(memory.id, label))
      .catch((error) => onDecision(memory.id, error instanceof Error ? error.message : "MemWing update failed"));
  }
  return (
    <section className="curve-review-row curve-review-row--memory">
      <FileText size={17} />
      <span>{memory.title}</span>
      <StrengthMeter value={memory.forgetting.decayScore} compact />
      <StatusPill label={decision ?? curveStateLabel(dictionary, memory.forgetting.curveState)} tone={memory.forgetting.curveState === "below_threshold" ? "red" : "orange"} />
      <small>next review {memory.forgetting.nextReviewAt ?? "none"}</small>
      <div className="inline-action-row">
        <button type="button" onClick={() => runAction("review", "Review requested")}>review</button>
        <button type="button" onClick={() => runAction("pin", "Pinned")}>pin</button>
        <button type="button" onClick={() => runAction("archive", "Archived")}>archive</button>
      </div>
    </section>
  );
}
