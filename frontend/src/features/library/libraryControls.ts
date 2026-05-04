import { curveStateLabel, lifecycleLabel, memoryTypeLabel } from "../../shared/i18n/formatters";
import type { LocaleDictionary } from "../../shared/i18n/locales/zh-CN";
import type { MemoryItem } from "../../shared/types/entities";

export function filterLibraryMemories({
  memories,
  filters,
  savedView,
  searchQuery,
  sortDescending,
  dictionary,
}: {
  memories: MemoryItem[];
  filters: Record<string, string>;
  savedView: string;
  searchQuery: string;
  sortDescending: boolean;
  dictionary: LocaleDictionary;
}) {
  return memories
    .filter((memory) => memoryMatchesSearch(memory, searchQuery))
    .filter((memory) => memoryMatchesFilters(memory, filters, savedView, dictionary))
    .sort((a, b) => sortDescending ? b.lastSeen.localeCompare(a.lastSeen) : a.lastSeen.localeCompare(b.lastSeen));
}

export function exportLibraryMemoriesCsv(records: MemoryItem[]) {
  const rows = [
    ["id", "title", "type", "status", "source", "last_seen", "strength", "flags"],
    ...records.map((memory) => [
      memory.id,
      memory.title,
      memory.type,
      memory.status,
      memory.source,
      memory.lastSeen,
      memory.strength.toFixed(4),
      memory.flags.join("|"),
    ]),
  ];
  const csv = rows.map((row) => row.map(csvCell).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `memwing-library-${Date.now()}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function memoryMatchesSearch(memory: MemoryItem, query: string) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }
  return [
    memory.id,
    memory.title,
    memory.reason,
    memory.source,
    memory.type,
    memory.status,
    memory.flags.join(" "),
  ].some((value) => value.toLowerCase().includes(normalizedQuery));
}

function memoryMatchesFilters(
  memory: MemoryItem,
  filters: Record<string, string>,
  savedView: string,
  dictionary: LocaleDictionary,
) {
  if (!matchesSavedView(memory, savedView)) {
    return false;
  }
  return Object.entries(filters).every(([key, value]) => matchesFilter(memory, key, value, dictionary));
}

function matchesSavedView(memory: MemoryItem, savedView: string) {
  if (savedView === "Review Due") {
    return memory.flags.includes("needs_review") || memory.forgetting.nextReviewAt !== null;
  }
  if (savedView === "Pinned") {
    return memory.flags.includes("pinned");
  }
  if (savedView === "Fading") {
    return memory.forgetting.curveState === "fading" || memory.forgetting.curveState === "below_threshold";
  }
  return true;
}

function matchesFilter(
  memory: MemoryItem,
  key: string,
  value: string,
  dictionary: LocaleDictionary,
) {
  const options = dictionary.library.filterOptions;
  if (value === options.any) {
    return true;
  }
  if (key === "type") {
    return value === memoryTypeLabel(dictionary, memory.type);
  }
  if (key === "lifecycle") {
    return value === lifecycleLabel(dictionary, memory.status);
  }
  if (key === "strength") {
    return value === strengthBucket(memory.strength, options);
  }
  if (key === "pinned") {
    return value === options.pinnedOnly ? memory.flags.includes("pinned") : !memory.flags.includes("pinned");
  }
  if (key === "archived") {
    return value === options.archivedOnly ? memory.status === "archived" : memory.status !== "archived";
  }
  if (key === "hidden") {
    return value === options.hiddenOnly ? memory.status === "hidden" : memory.status !== "hidden";
  }
  if (key === "needsReview") {
    const needsReview = memory.flags.includes("needs_review") || memory.forgetting.nextReviewAt !== null;
    return value === options.reviewDue ? needsReview : !needsReview;
  }
  if (key === "time") {
    return matchesTime(memory.lastSeen, value, options);
  }
  if (key === "sourcePlatform" || key === "project" || key === "group" || key === "thread") {
    return memory.source.toLowerCase().includes(value.toLowerCase());
  }
  return curveStateLabel(dictionary, memory.forgetting.curveState).toLowerCase().includes(value.toLowerCase());
}

function strengthBucket(strength: number, options: LocaleDictionary["library"]["filterOptions"]) {
  if (strength >= 0.75) {
    return options.high;
  }
  if (strength >= 0.45) {
    return options.medium;
  }
  return options.low;
}

function matchesTime(lastSeen: string, value: string, options: LocaleDictionary["library"]["filterOptions"]) {
  const time = Date.parse(lastSeen);
  if (!Number.isFinite(time)) {
    return false;
  }
  const ageDays = (Date.now() - time) / 86_400_000;
  if (value === options.today) {
    return ageDays <= 1;
  }
  if (value === options.last7Days) {
    return ageDays <= 7;
  }
  return ageDays > 7;
}

function csvCell(value: string) {
  return `"${value.replace(/"/g, "\"\"")}"`;
}
