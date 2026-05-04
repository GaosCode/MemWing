import type { LifecycleStatus, MemoryType, Severity } from "./lifecycle";

export type NavKey = "inbox" | "library" | "project" | "maintenance" | "settings";

export type DetailMode = "memory" | "project" | "maintenance" | null;

export type MemoryItem = {
  id: string;
  title: string;
  type: MemoryType;
  source: string;
  groupId: string | null;
  threadId: string | null;
  sourceState: string;
  sourceEventIds: string[];
  lastSeen: string;
  status: LifecycleStatus;
  strength: number;
  flags: string[];
  reason: string;
  forgetting: ForgettingCurve;
};

export type CurveState =
  | "retained"
  | "fading"
  | "below_threshold"
  | "pinned"
  | "archived"
  | "hidden"
  | "invalid"
  | "removed";

export type ForgettingCurve = {
  decayScore: number;
  originalScore: number;
  halfLifeDays: number;
  recallThreshold: number;
  lastReinforcedAt: string;
  nextReviewAt: string | null;
  retentionReason: string;
  curveState: CurveState;
  curvePoints: Array<{ day: number; score: number }>;
};

export type MaintenanceItem = {
  id: string;
  actionKind: "job" | "push_candidate" | "review";
  jobKind?: string;
  retryable?: boolean;
  sourceEventIds?: string[];
  memoryItemIds?: string[];
  type: string;
  title: string;
  source: string;
  reason: string;
  state: "Failed" | "Review Pending" | "Ready to forget" | "Open" | "Approved" | "Sent" | "Skipped";
  updated: string;
  severity: Severity;
};
