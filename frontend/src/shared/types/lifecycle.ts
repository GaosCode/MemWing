export type LifecycleStatus =
  | "active"
  | "candidate"
  | "fading"
  | "needs_review"
  | "archived"
  | "hidden"
  | "invalid";

export type Severity = "low" | "medium" | "high" | "failed" | "warning" | "healthy";

export type MemoryType = "preference" | "decision" | "policy" | "risk" | "constraint" | "summary";

export type QueueState = "running" | "paused" | "failed";
