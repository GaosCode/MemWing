import { CircleAlert, RefreshCcw } from "lucide-react";
import { Button, StatusPill } from "../../shared/components/ui";
import type { ControlPageDto } from "../../api/generated/controlPlane";

export function ProjectReviewPanel({
  page,
  updating,
  onRebuild,
  onOpenSources,
}: {
  page: ControlPageDto;
  updating: boolean;
  onRebuild: () => void;
  onOpenSources: () => void;
}) {
  return (
    <div className="project-tab-panel">
      <div className="section-toolbar section-toolbar--flush">
        <div>
          <h2>Rebuild Status</h2>
          <p className="section-subtitle">Manual rebuild calls the Page Memory backend and writes the next page version when synthesis succeeds.</p>
        </div>
        <Button primary icon={RefreshCcw} label={updating ? "Rebuilding" : "Run Rebuild"} onClick={onRebuild} disabled={updating} />
      </div>
      <div className="push-candidate-summary">
        <section>
          <span>Current version</span>
          <strong>v{page.version}</strong>
          <p>{page.updated_at}</p>
        </section>
        <section>
          <span>Needs rebuild</span>
          <strong>{page.needs_rebuild ? "Yes" : "No"}</strong>
          <p>{page.needs_rebuild ? "A source window or linked input changed." : "Backend does not require a rebuild for this scope."}</p>
        </section>
        <section>
          <span>Warnings</span>
          <strong>{page.warning_count}</strong>
          <p>{page.graph_backend_raw_retained ? "Some source raw text remains in graph backend." : "No graph raw-retention warning from linked sources."}</p>
        </section>
      </div>
      <TopicChangeList page={page} onOpenSources={onOpenSources} />
      <div className="project-preview-note">
        <CircleAlert size={18} />
        <span>Rebuild is persisted by the backend; this screen refreshes from the returned Page Memory detail.</span>
      </div>
    </div>
  );
}

function TopicChangeList({ page, onOpenSources }: { page: ControlPageDto; onOpenSources: () => void }) {
  return (
    <div className="action-list action-list--maintenance">
      {page.topics.map((topic) => (
        <section key={topic.title} className="action-list-row action-list-row--push-candidate">
          <StatusPill label="Topic" tone="green" />
          <span>{topic.title}</span>
          <strong>{topic.summary}</strong>
          <span>{topic.source_event_ids.length} sources</span>
          <button type="button" onClick={onOpenSources}>sources</button>
        </section>
      ))}
      {page.topics.length === 0 ? <p>No topic projection has been generated for this page.</p> : null}
    </div>
  );
}
