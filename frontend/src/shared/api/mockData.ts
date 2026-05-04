import { memoryListFixtureResponse } from "../../api/generated/memoryList";
import { memoryListItemToViewModel } from "../../api/mappers/memoryList";
import type { MaintenanceItem, MemoryItem } from "../types/entities";

export const memories: MemoryItem[] =
  memoryListFixtureResponse.items.map(memoryListItemToViewModel);

export const maintenanceItems: MaintenanceItem[] = [
  {
    id: "mock_failed_job",
    actionKind: "job",
    jobKind: "outbox",
    retryable: true,
    type: "Failed Job",
    title: "PushWorker failed to promote candidate",
    source: "Project Memory",
    reason: "conflict threshold exceeded",
    state: "Failed",
    updated: "11:15",
    severity: "failed",
  },
  {
    id: "mock_review_1",
    actionKind: "review",
    type: "Review",
    title: "用户希望自动维护动作可解释、可撤销",
    source: "Feishu · 产品群",
    reason: "repeated preference",
    state: "Review Pending",
    updated: "11:32",
    severity: "warning",
  },
  {
    id: "mock_review_2",
    actionKind: "review",
    type: "Review",
    title: "Current Stage wording alignment",
    source: "Page Memory",
    reason: "project wording drift",
    state: "Review Pending",
    updated: "11:05",
    severity: "warning",
  },
  {
    id: "mock_forgetting_1",
    actionKind: "review",
    type: "Forgetting",
    title: "过时的 duplicate risk wording",
    source: "Project Memory",
    reason: "superseded by v3 wording",
    state: "Ready to forget",
    updated: "10:33",
    severity: "healthy",
  },
  {
    id: "mock_push_1",
    actionKind: "push_candidate",
    type: "Push",
    title: "Inspector remains compact preview",
    source: "Project Memory",
    reason: "3 sources",
    state: "Open",
    updated: "10:15",
    severity: "healthy",
  },
];
