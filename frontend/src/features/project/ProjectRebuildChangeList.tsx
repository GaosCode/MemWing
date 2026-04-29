import { StatusPill } from "../../shared/components/ui";
import { rebuildChanges } from "./projectData";

function toneForChange(tone: (typeof rebuildChanges)[number]["tone"]) {
  if (tone === "success") {
    return "green";
  }
  if (tone === "warning") {
    return "orange";
  }
  return "red";
}

export function ProjectRebuildChangeList({
  onOpenSources,
  embedded,
}: {
  onOpenSources: () => void;
  embedded?: boolean;
}) {
  return (
    <div className={`review-change-list ${embedded ? "review-change-list--embedded" : ""}`}>
      <div className="review-change-row review-change-row--head">
        <span>Type</span>
        <span>Candidate change</span>
        <span>Sources</span>
        <span>Confidence</span>
        <span>Evidence</span>
      </div>
      {rebuildChanges.map((change) => (
        <section key={change.type} className="review-change-row">
          <StatusPill label={change.type} tone={toneForChange(change.tone)} />
          <strong>{change.summary}</strong>
          <span>{change.sources}</span>
          <span>{change.confidence}</span>
          <button type="button" onClick={onOpenSources}>view sources</button>
        </section>
      ))}
    </div>
  );
}
