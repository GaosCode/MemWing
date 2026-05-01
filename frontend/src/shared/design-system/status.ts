import type { LifecycleStatus, MemoryType, Severity } from "../types/lifecycle";

export type StatusTone = "green" | "orange" | "red" | "gray";

export const lifecycleTone: Record<LifecycleStatus, StatusTone> = {
  active: "green",
  candidate: "green",
  fading: "orange",
  needs_review: "orange",
  archived: "gray",
  hidden: "gray",
  invalid: "red",
  removed: "red",
};

export const severityTone: Record<Severity, StatusTone> = {
  low: "green",
  medium: "orange",
  high: "red",
  failed: "red",
  warning: "orange",
  healthy: "green",
};

export const memoryTypeTone: Record<MemoryType, StatusTone> = {
  decision: "gray",
  task: "gray",
  preference: "gray",
  rule: "gray",
  note: "gray",
  evidence: "gray",
};
