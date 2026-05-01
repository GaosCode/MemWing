import type { MaintenanceItem } from "../types/entities";
import type { CurveState } from "../types/entities";
import type { LifecycleStatus, MemoryType, Severity } from "../types/lifecycle";
import type { LocaleDictionary } from "./locales/zh-CN";

export function lifecycleLabel(dictionary: LocaleDictionary, status: LifecycleStatus) {
  return dictionary.status.lifecycle[status].label;
}

export function lifecycleDescription(dictionary: LocaleDictionary, status: LifecycleStatus) {
  return dictionary.status.lifecycle[status].description;
}

export function severityLabel(dictionary: LocaleDictionary, severity: Severity) {
  return dictionary.status.severity[severity];
}

export function memoryTypeLabel(dictionary: LocaleDictionary, type: MemoryType) {
  return dictionary.status.memoryType[type];
}

export function maintenanceStateLabel(dictionary: LocaleDictionary, state: MaintenanceItem["state"]) {
  return dictionary.status.maintenanceState[state];
}

export function curveStateLabel(dictionary: LocaleDictionary, state: CurveState) {
  return dictionary.status.curveState[state];
}
