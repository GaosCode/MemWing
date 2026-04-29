import { useState } from "react";
import { Check, RefreshCcw, ShieldCheck } from "lucide-react";
import { Button, PageHeader, StatusPill } from "../../shared/components/ui";

const initialSettings = [
  { title: "Project Space", value: "产品记忆治理", body: "Default workspace for current memory governance.", mutable: false },
  { title: "OpenClaw Integration", value: "Connected", body: "ContextEngine hooks are ready for ingest, assemble, and compact.", mutable: false },
  { title: "Feishu Integration", value: "Connected", body: "Webhook verification and source preview are enabled.", mutable: false },
  { title: "Graph Backend", value: "GraphitiAdapter", body: "Core contracts stay backend-neutral.", mutable: false },
  { title: "LLM Filter", value: "Enabled", body: "Candidate extraction and review suggestions are queued.", mutable: true },
  { title: "Safety", value: "safe_mode off", body: "Cross-group recall stays controlled by configured scope rules.", mutable: true },
  { title: "Automation", value: "Queue running", body: "Background jobs update status without modal interruptions.", mutable: true },
  { title: "Debug", value: "Collapsed", body: "Raw ids are hidden unless debug mode is opened.", mutable: true },
];

export function SettingsPage() {
  const [settings, setSettings] = useState(initialSettings);
  const [notice, setNotice] = useState("Settings are loaded");

  function toggleSetting(title: string) {
    setSettings((current) => current.map((setting) => {
      if (setting.title !== title || !setting.mutable) {
        return setting;
      }

      const nextValue: Record<string, string> = {
        "LLM Filter": setting.value === "Enabled" ? "Disabled" : "Enabled",
        Safety: setting.value === "safe_mode off" ? "safe_mode on" : "safe_mode off",
        Automation: setting.value === "Queue running" ? "Queue paused" : "Queue running",
        Debug: setting.value === "Collapsed" ? "Expanded" : "Collapsed",
      };

      return { ...setting, value: nextValue[title] ?? setting.value };
    }));
    setNotice(`${title} updated locally`);
  }

  return (
    <section className="settings-page">
      <PageHeader
        title="Settings"
        subtitle="Configure integrations, safety boundaries, automation behavior, and debug visibility."
        actions={
          <>
            <Button icon={RefreshCcw} label="Test Connections" onClick={() => setNotice("Integration checks passed")} />
            <Button primary icon={ShieldCheck} label="Save Settings" onClick={() => setNotice("Settings saved locally")} />
          </>
        }
      />
      <div className="notice-row"><Check size={15} />{notice}</div>
      <div className="settings-grid">
        {settings.map(({ title, value, body, mutable }) => (
          <button className="settings-section" type="button" key={title} onClick={() => toggleSetting(title)} disabled={!mutable}>
            <div>
              <h2>{title}</h2>
              <StatusPill label={value} tone={settingTone(value)} />
            </div>
            <p>{body}</p>
            <span className="settings-action">{mutable ? "Toggle" : "Locked"}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function settingTone(value: string) {
  if (value.includes("off") || value.includes("paused")) {
    return "orange" as const;
  }
  if (value === "Disabled") {
    return "gray" as const;
  }
  return "green" as const;
}
