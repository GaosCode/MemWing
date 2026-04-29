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
  forgetting: ForgettingCurve;
};

export type CurveState = "stable" | "fading" | "review_due" | "ready_to_forget" | "pinned";

export type ForgettingCurve = {
  decayScore: number;
  originalScore: number;
  halfLifeDays: number;
  recallThreshold: number;
  lastReinforcedAt: string;
  nextReviewAt: string;
  retentionReason: string;
  curveState: CurveState;
  curvePoints: Array<{ day: number; score: number }>;
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
