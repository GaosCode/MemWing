export type LifecycleStatus =
  | "active"
  | "candidate"
  | "fading"
  | "needs_review"
  | "archived"
  | "hidden"
  | "invalid"
  | "removed";

export type Severity = "low" | "medium" | "high" | "failed" | "warning" | "healthy";

export type MemoryType = "decision" | "task" | "preference" | "rule" | "note" | "evidence";

export type QueueState = "running" | "paused" | "failed";
