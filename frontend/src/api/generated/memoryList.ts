import memoryListFixture from "../../../../shared_contracts/memory_list.fixture.json";

export type MemoryDisplayType = "decision" | "task" | "preference" | "rule" | "note" | "evidence";

export type MemoryStatus =
  | "candidate"
  | "active"
  | "fading"
  | "archived"
  | "hidden"
  | "invalid"
  | "needs_review"
  | "removed";

export type MemoryListItemDto = {
  id: string;
  title: string;
  display_type: MemoryDisplayType;
  source_label: string;
  last_seen: string;
  status: MemoryStatus;
  strength: number;
  flags: string[];
  reason: string;
};

export type MemoryListResponseDto = {
  items: MemoryListItemDto[];
  next_cursor: string | null;
  trace_id: string;
};

const displayTypes: readonly MemoryDisplayType[] = [
  "decision",
  "task",
  "preference",
  "rule",
  "note",
  "evidence",
];

const memoryStatuses: readonly MemoryStatus[] = [
  "candidate",
  "active",
  "fading",
  "archived",
  "hidden",
  "invalid",
  "needs_review",
  "removed",
];

export function parseMemoryListResponse(input: unknown): MemoryListResponseDto {
  const object = requireRecord(input, "memory list response");
  const items = object.items;
  if (!Array.isArray(items)) {
    throw new Error("items must be an array");
  }
  const nextCursor = object.next_cursor;
  if (nextCursor !== null && typeof nextCursor !== "string") {
    throw new Error("next_cursor must be text or null");
  }
  return {
    items: items.map(parseMemoryListItem),
    next_cursor: nextCursor,
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

function parseMemoryListItem(input: unknown): MemoryListItemDto {
  const object = requireRecord(input, "memory list item");
  const flags = object.flags;
  if (!Array.isArray(flags) || !flags.every((flag) => typeof flag === "string")) {
    throw new Error("flags must be a string array");
  }
  return {
    id: requireText(object.id, "id"),
    title: requireText(object.title, "title"),
    display_type: requireEnum(object.display_type, displayTypes, "display_type"),
    source_label: requireText(object.source_label, "source_label"),
    last_seen: requireText(object.last_seen, "last_seen"),
    status: requireEnum(object.status, memoryStatuses, "status"),
    strength: requireNumber(object.strength, "strength"),
    flags: [...flags],
    reason: requireText(object.reason, "reason"),
  };
}

function requireRecord(input: unknown, field: string): Record<string, unknown> {
  if (input === null || typeof input !== "object" || Array.isArray(input)) {
    throw new Error(`${field} must be an object`);
  }
  return input as Record<string, unknown>;
}

function requireText(input: unknown, field: string): string {
  if (typeof input !== "string" || input.trim().length === 0) {
    throw new Error(`${field} must be text`);
  }
  return input;
}

function requireNumber(input: unknown, field: string): number {
  if (typeof input !== "number" || !Number.isFinite(input)) {
    throw new Error(`${field} must be a number`);
  }
  return input;
}

function requireEnum<T extends string>(
  input: unknown,
  allowed: readonly T[],
  field: string,
): T {
  if (typeof input !== "string" || !allowed.includes(input as T)) {
    throw new Error(`${field} is not supported`);
  }
  return input as T;
}

export const memoryListFixtureResponse = parseMemoryListResponse(memoryListFixture);
