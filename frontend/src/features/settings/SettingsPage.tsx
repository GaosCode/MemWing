import { useState } from "react";
import { Check, RefreshCcw, ShieldCheck } from "lucide-react";
import { Button, PageHeader, StatusPill } from "../../shared/components/ui";
import { useI18n } from "../../shared/i18n";

type SettingKey = "projectSpace" | "openClaw" | "feishu" | "graphBackend" | "llmFilter" | "safety" | "automation" | "debug";

const initialSettings: Array<{ key: SettingKey; value: string; mutable: boolean }> = [
  { key: "projectSpace", value: "产品记忆治理", mutable: false },
  { key: "openClaw", value: "Connected", mutable: false },
  { key: "feishu", value: "Connected", mutable: false },
  { key: "graphBackend", value: "GraphitiAdapter", mutable: false },
  { key: "llmFilter", value: "Enabled", mutable: true },
  { key: "safety", value: "safe_mode off", mutable: true },
  { key: "automation", value: "Queue running", mutable: true },
  { key: "debug", value: "Collapsed", mutable: true },
];

export function SettingsPage() {
  const { dictionary } = useI18n();
  const [settings, setSettings] = useState(initialSettings);
  const [notice, setNotice] = useState(dictionary.settings.loaded);

  function toggleSetting(key: SettingKey) {
    setSettings((current) => current.map((setting) => {
      if (setting.key !== key || !setting.mutable) {
        return setting;
      }

      const nextValue: Record<string, string> = {
        llmFilter: setting.value === "Enabled" ? "Disabled" : "Enabled",
        safety: setting.value === "safe_mode off" ? "safe_mode on" : "safe_mode off",
        automation: setting.value === "Queue running" ? "Queue paused" : "Queue running",
        debug: setting.value === "Collapsed" ? "Expanded" : "Collapsed",
      };

      return { ...setting, value: nextValue[key] ?? setting.value };
    }));
    setNotice(`${dictionary.settings.sections[key].title} updated locally`);
  }

  return (
    <section className="settings-page">
      <PageHeader
        title={dictionary.settings.title}
        subtitle={dictionary.settings.subtitle}
        actions={
          <>
            <Button icon={RefreshCcw} label={dictionary.actions.testConnections} onClick={() => setNotice(dictionary.settings.checksPassed)} />
            <Button primary icon={ShieldCheck} label={dictionary.actions.saveSettings} onClick={() => setNotice(dictionary.settings.saved)} />
          </>
        }
      />
      <div className="notice-row"><Check size={15} />{notice}</div>
      <div className="settings-grid">
        {settings.map(({ key, value, mutable }) => (
          <button className="settings-section" type="button" key={key} onClick={() => toggleSetting(key)} disabled={!mutable}>
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

function settingTone(value: string) {
  if (value.includes("off") || value.includes("paused")) {
    return "orange" as const;
  }
  if (value === "Disabled") {
    return "gray" as const;
  }
  return "green" as const;
}
