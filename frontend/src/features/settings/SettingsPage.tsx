import { PageHeader, StatusPill } from "../../shared/components/ui";

const settings = [
  ["Project Space", "产品记忆治理", "Default workspace for current memory governance."],
  ["OpenClaw Integration", "Connected", "ContextEngine hooks are ready for ingest, assemble, and compact."],
  ["Feishu Integration", "Connected", "Webhook verification and source preview are enabled."],
  ["Graph Backend", "GraphitiAdapter", "Core contracts stay backend-neutral."],
  ["LLM Filter", "Enabled", "Candidate extraction and review suggestions are queued."],
  ["Safety", "safe_mode off", "Cross-group recall stays controlled by configured scope rules."],
  ["Automation", "Queue running", "Background jobs update status without modal interruptions."],
  ["Debug", "Collapsed", "Raw ids are hidden unless debug mode is opened."],
];

export function SettingsPage() {
  return (
    <section className="settings-page">
      <PageHeader
        title="Settings"
        subtitle="Configure integrations, safety boundaries, automation behavior, and debug visibility."
      />
      <div className="settings-grid">
        {settings.map(([title, value, body]) => (
          <section className="settings-section" key={title}>
            <div>
              <h2>{title}</h2>
              <StatusPill label={value} tone={value.includes("off") ? "orange" : "green"} />
            </div>
            <p>{body}</p>
          </section>
        ))}
      </div>
    </section>
  );
}
