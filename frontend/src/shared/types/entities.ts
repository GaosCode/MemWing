import type { LifecycleStatus, MemoryType, Severity } from "./lifecycle";

export type NavKey = "inbox" | "library" | "project" | "maintenance" | "settings";

export type DetailMode = "memory" | "project" | "maintenance" | null;

export type MemoryItem = {
  id: string;
  title: string;
  type: MemoryType;
  source: string;
  lastSeen: string;
  status: LifecycleStatus;
  strength: number;
  flags: string[];
  reason: string;
};

export type MaintenanceItem = {
  type: string;
  title: string;
  source: string;
  reason: string;
  state: "Failed" | "Review Pending" | "Ready to forget" | "Open";
  updated: string;
  severity: Severity;
};
