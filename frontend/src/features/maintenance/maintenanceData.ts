export const workerHealthRows = [
  { worker: "LongTermFilter", status: "Healthy", lastRun: "11:32", failures: 0, duration: "1.2s", queue: "memory.filter", note: "Micro-batch completed" },
  { worker: "GraphWriteWorker", status: "Warning", lastRun: "11:30", failures: 1, duration: "2.8s", queue: "graph.write", note: "Backpressure from GraphBackend" },
  { worker: "PageMemoryWorker", status: "Healthy", lastRun: "11:28", failures: 0, duration: "3.1s", queue: "page.rebuild", note: "No pending rebuilds" },
  { worker: "DecayWorker", status: "Healthy", lastRun: "11:20", failures: 0, duration: "1.7s", queue: "memory.decay", note: "2 items near review threshold" },
  { worker: "PushWorker", status: "Failed", lastRun: "11:15", failures: 2, duration: "4.6s", queue: "maintenance.push", note: "Conflict threshold exceeded" },
] as const;

export const jobHistoryRows = [
  { time: "11:32", worker: "LongTermFilter", status: "Succeeded", title: "Refreshed memory strengths", detail: "14 memories refreshed" },
  { time: "11:15", worker: "PushWorker", status: "Failed", title: "Promotion blocked", detail: "Conflict threshold exceeded" },
  { time: "11:05", worker: "PushWorker", status: "Skipped", title: "Promotion skipped", detail: "Pending review" },
  { time: "10:33", worker: "DecayWorker", status: "Warning", title: "Forgetting review completed", detail: "2 ready to forget" },
  { time: "10:15", worker: "PageMemoryWorker", status: "Succeeded", title: "Project rebuild preview generated", detail: "3 candidate changes" },
] as const;

export const linkedReferences = [
  { label: "source_events", count: "5 events" },
  { label: "memory_items", count: "3 items" },
  { label: "memory_pages", count: "1 page" },
  { label: "audit_events", count: "2 events" },
] as const;

export const retryHistoryRows = [
  "11:15 Failed · conflict threshold exceeded",
  "11:05 Skipped · pending review",
  "10:33 Warning · stale candidate state",
] as const;

export const auditTrailRows = [
  "11:15 Promotion blocked",
  "11:15 Conflict audit linked",
  "11:14 Candidate selected",
  "11:12 Worker queue started",
] as const;
