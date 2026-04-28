import type { LifecycleStatus, MemoryType, Severity } from "../types/lifecycle";

export const lifecycleStatus: Record<
  LifecycleStatus,
  { label: string; tone: "green" | "orange" | "red" | "gray"; description: string }
> = {
  active: {
    label: "Active",
    tone: "green",
    description: "参与当前召回，可继续作为长期记忆使用。",
  },
  candidate: {
    label: "Candidate",
    tone: "green",
    description: "候选记忆，需要人工确认后进入稳定状态。",
  },
  fading: {
    label: "Fading",
    tone: "orange",
    description: "强度正在下降，建议复习、固定或归档。",
  },
  needs_review: {
    label: "Needs Review",
    tone: "orange",
    description: "存在冲突或证据不足，需要人工复核。",
  },
  archived: {
    label: "Archived",
    tone: "gray",
    description: "已归档，不作为默认召回材料。",
  },
  hidden: {
    label: "Hidden",
    tone: "gray",
    description: "已隐藏，保留审计记录但不默认展示。",
  },
  invalid: {
    label: "Invalid",
    tone: "red",
    description: "已失效，不能继续作为可信记忆使用。",
  },
};

export const severityStatus: Record<Severity, { label: string; tone: "green" | "orange" | "red" | "gray" }> = {
  low: { label: "Low", tone: "green" },
  medium: { label: "Medium", tone: "orange" },
  high: { label: "High", tone: "red" },
  failed: { label: "Failed", tone: "red" },
  warning: { label: "Warning", tone: "orange" },
  healthy: { label: "Healthy", tone: "green" },
};

export const memoryTypeLabel: Record<MemoryType, string> = {
  preference: "Preference",
  decision: "Decision",
  policy: "Policy",
  risk: "Risk",
  constraint: "Constraint",
  summary: "Summary",
};
