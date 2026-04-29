export const rebuildChanges = [
  { type: "Add", tone: "success", summary: "Next Steps now include project memory drift checks.", sources: "2 sources", confidence: "0.86" },
  { type: "Revise", tone: "warning", summary: "Current Stage updated to A3 Calm Operations consolidation.", sources: "3 sources", confidence: "0.84" },
  { type: "Remove", tone: "danger", summary: "Older duplicate risk wording removed.", sources: "1 source", confidence: "0.79" },
] as const;

export const projectSources = [
  { name: "Feishu · 产品群", events: 14, lastSeen: "2026-04-27 11:32", coverage: "High", status: "Linked", use: "Product decisions and maintenance preferences" },
  { name: "Feishu · 安全群", events: 5, lastSeen: "2026-04-27 10:33", coverage: "Medium", status: "Linked", use: "Safety constraints and redaction notes" },
  { name: "AI 产品自动化维护", events: 3, lastSeen: "2026-04-27 10:15", coverage: "Medium", status: "Needs review", use: "Automation behavior and worker expectations" },
  { name: "Others", events: 2, lastSeen: "2026-04-26 18:44", coverage: "Low", status: "Watched", use: "Historical fallback evidence" },
] as const;

export const projectVersions = [
  { version: "v3", label: "current", time: "2026-04-27 11:32", author: "swift.gao", summary: "A3 Calm Operations consolidation", state: "Current" },
  { version: "v2", label: "previous", time: "2026-04-27 11:05", author: "PageMemoryWorker", summary: "Current Stage revised", state: "Restorable" },
  { version: "v1", label: "initial", time: "2026-04-27 10:15", author: "LongTermFilter", summary: "Initial project memory captured", state: "Restorable" },
] as const;

export const auditEvents = [
  { time: "11:32", type: "Rebuild", title: "Rebuild preview generated", actor: "PageMemoryWorker" },
  { time: "11:21", type: "Evidence", title: "Source event linked", actor: "Feishu · 产品群" },
  { time: "11:05", type: "Version", title: "Project stage revised", actor: "swift.gao" },
  { time: "10:33", type: "Conflict", title: "Conflict scan completed", actor: "ConflictScanWorker" },
  { time: "10:15", type: "Capture", title: "Initial project memory captured", actor: "LongTermFilter" },
] as const;
