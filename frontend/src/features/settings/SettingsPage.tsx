import { useMemo, useState } from "react";
import { Check, RefreshCcw, ShieldCheck } from "lucide-react";
import { Button, PageHeader, StatusPill } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";
import type { ControlIntegrationsResponseDto, ControlSettingsDto } from "../../api/generated/controlPlane";

type SettingKey = "projectSpace" | "openClaw" | "feishu" | "graphBackend" | "llmFilter" | "safety" | "automation" | "debug";

export function SettingsPage({
  settings,
  integrations,
  onRefresh,
}: {
  settings: ControlSettingsDto | null;
  integrations: ControlIntegrationsResponseDto | null;
  onRefresh: () => void;
}) {
  const { dictionary } = useI18n();
  const [notice, setNotice] = useState(dictionary.settings.loaded);
  const rows = useMemo(() => settingsRows(settings, integrations), [settings, integrations]);

  function refresh() {
    onRefresh();
    setNotice(dictionary.settings.checksPassed);
  }

  return (
    <section className="settings-page">
      <PageHeader
        title={dictionary.settings.title}
        subtitle={dictionary.settings.subtitle}
        actions={
          <>
            <Button icon={RefreshCcw} label={dictionary.actions.testConnections} onClick={refresh} />
            <Button primary icon={ShieldCheck} label={dictionary.actions.saveSettings} onClick={() => setNotice("Settings mutation is not enabled by the backend contract")} disabled={!settings?.settings_mutation_supported} />
          </>
        }
      />
      <div className="notice-row"><Check size={15} />{notice}</div>
      <div className="settings-grid">
        {rows.map(({ key, value, mutable }) => (
          <button className="settings-section" type="button" key={key} onClick={() => setNotice(`${dictionary.settings.sections[key].title}: ${value}`)} disabled={!mutable}>
            <div>
              <h2>{dictionary.settings.sections[key].title}</h2>
              <StatusPill label={value} tone={settingTone(value)} />
            </div>
            <p>{dictionary.settings.sections[key].body}</p>
            <span className="settings-action">{mutable ? dictionary.settings.toggle : dictionary.settings.locked}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function settingsRows(
  settings: ControlSettingsDto | null,
  integrations: ControlIntegrationsResponseDto | null,
): Array<{ key: SettingKey; value: string; mutable: boolean }> {
  const integration = (name: string) => integrations?.items.find((item) => item.name === name);
  const integrationValue = (name: string) => {
    const item = integration(name);
    if (item === undefined) {
      return "Unavailable";
    }
    return item.configured ? "Connected" : "Not configured";
  };
  return [
    { key: "projectSpace", value: settings?.project_memory_space_id ?? "Unavailable", mutable: false },
    { key: "openClaw", value: integrationValue("openclaw"), mutable: Boolean(integration("openclaw")?.writable) },
    { key: "feishu", value: integrationValue("feishu"), mutable: Boolean(integration("feishu")?.writable) },
    { key: "graphBackend", value: integrationValue("graph_backend"), mutable: Boolean(integration("graph_backend")?.writable) },
    { key: "llmFilter", value: integrationValue("llm_filter"), mutable: Boolean(integration("llm_filter")?.writable) },
    { key: "safety", value: settings?.safe_mode_enabled ? "safe_mode on" : "safe_mode off", mutable: Boolean(settings?.settings_mutation_supported) },
    { key: "automation", value: settings?.settings_mutation_supported ? "Writable" : "Read-only", mutable: Boolean(settings?.settings_mutation_supported) },
    { key: "debug", value: integrations?.trace_id ?? "Collapsed", mutable: false },
  ];
}

function settingTone(value: string) {
  if (value.includes("off") || value.includes("paused") || value === "Read-only") {
    return "orange" as const;
  }
  if (value === "Disabled" || value === "Unavailable" || value === "Not configured") {
    return "gray" as const;
  }
  return "green" as const;
}
