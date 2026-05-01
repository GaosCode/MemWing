import memoryListFixture from "../../../../shared_contracts/memory_list.fixture.json";

export type MemoryDisplayType = "decision" | "task" | "preference" | "rule" | "note" | "evidence";
export type MemoryRoute = "graph" | "vector_only" | "raw_only" | "manual";

export type MemoryStatus =
  | "candidate"
  | "active"
  | "fading"
  | "archived"
  | "hidden"
  | "invalid"
  | "needs_review"
  | "removed";

export type CurveState =
  | "retained"
  | "fading"
  | "below_threshold"
  | "pinned"
  | "archived"
  | "hidden"
  | "invalid"
  | "removed";

export type MemoryListItemDto = {
  id: string;
  title: string;
  summary: string | null;
  display_type: MemoryDisplayType;
  route: MemoryRoute;
  status: MemoryStatus;
  group_id: string | null;
  thread_id: string | null;
  source_event_ids: string[];
  decay_score: number;
  original_score: number;
  half_life_days: number;
  recall_threshold: number;
  curve_state: CurveState;
  last_reinforced_at: string;
  next_review_at: string | null;
  retention_reason: string;
  flags: string[];
  source_state: string;
  graph_backend_raw_retained: boolean;
  available_actions: string[];
  warning_count: number;
  updated_at: string;
};

export type MemoryListResponseDto = {
  items: MemoryListItemDto[];
  next_cursor: string | null;
  trace_id: string;
};

type ExactObject<T, Shape> =
  Exclude<keyof T, keyof Shape> extends never
    ? Exclude<keyof Shape, keyof T> extends never
      ? T
      : never
    : never;

type ExactMemoryListFixture<T extends { items: readonly unknown[] }> = ExactObject<
  T,
  MemoryListResponseDto
> & {
  items: T["items"] extends readonly (infer Item)[]
    ? ExactObject<Item, MemoryListItemDto>[]
    : never;
};

const memoryListFixtureContract: ExactMemoryListFixture<typeof memoryListFixture> =
  memoryListFixture;

const displayTypes: readonly MemoryDisplayType[] = [
  "decision",
  "task",
  "preference",
  "rule",
  "note",
  "evidence",
];

const memoryRoutes: readonly MemoryRoute[] = ["graph", "vector_only", "raw_only", "manual"];

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

const curveStates: readonly CurveState[] = [
  "retained",
  "fading",
  "below_threshold",
  "pinned",
  "archived",
  "hidden",
  "invalid",
  "removed",
];

export function parseMemoryListResponse(input: unknown): MemoryListResponseDto {
  const object = requireRecord(input, "memory list response");
  requireExactFields(object, ["items", "next_cursor", "trace_id"], "memory list response");
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
  requireExactFields(
    object,
    [
      "id",
      "title",
      "summary",
      "display_type",
      "route",
      "status",
      "group_id",
      "thread_id",
      "source_event_ids",
      "decay_score",
      "original_score",
      "half_life_days",
      "recall_threshold",
      "curve_state",
      "last_reinforced_at",
      "next_review_at",
      "retention_reason",
      "flags",
      "source_state",
      "graph_backend_raw_retained",
      "available_actions",
      "warning_count",
      "updated_at",
    ],
    "memory list item",
  );
  return {
    id: requireText(object.id, "id"),
    title: requireText(object.title, "title"),
    summary: requireOptionalText(object.summary, "summary"),
    display_type: requireEnum(object.display_type, displayTypes, "display_type"),
    route: requireEnum(object.route, memoryRoutes, "route"),
    status: requireEnum(object.status, memoryStatuses, "status"),
    group_id: requireOptionalText(object.group_id, "group_id"),
    thread_id: requireOptionalText(object.thread_id, "thread_id"),
    source_event_ids: requireTextArray(object.source_event_ids, "source_event_ids"),
    decay_score: requireNumber(object.decay_score, "decay_score"),
    original_score: requireNumber(object.original_score, "original_score"),
    half_life_days: requireInteger(object.half_life_days, "half_life_days"),
    recall_threshold: requireNumber(object.recall_threshold, "recall_threshold"),
    curve_state: requireEnum(object.curve_state, curveStates, "curve_state"),
    last_reinforced_at: requireText(object.last_reinforced_at, "last_reinforced_at"),
    next_review_at: requireOptionalText(object.next_review_at, "next_review_at"),
    retention_reason: requireText(object.retention_reason, "retention_reason"),
    flags: requireTextArray(object.flags, "flags"),
    source_state: requireText(object.source_state, "source_state"),
    graph_backend_raw_retained: requireBoolean(
      object.graph_backend_raw_retained,
      "graph_backend_raw_retained",
    ),
    available_actions: requireTextArray(object.available_actions, "available_actions"),
    warning_count: requireInteger(object.warning_count, "warning_count"),
    updated_at: requireText(object.updated_at, "updated_at"),
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

function requireOptionalText(input: unknown, field: string): string | null {
  if (input === null) {
    return null;
  }
  return requireText(input, field);
}

function requireTextArray(input: unknown, field: string): string[] {
  if (!Array.isArray(input) || !input.every((item) => typeof item === "string")) {
    throw new Error(`${field} must be a string array`);
  }
  return [...input];
}

function requireNumber(input: unknown, field: string): number {
  if (typeof input !== "number" || !Number.isFinite(input)) {
    throw new Error(`${field} must be a number`);
  }
  return input;
}

function requireInteger(input: unknown, field: string): number {
  if (typeof input !== "number" || !Number.isInteger(input)) {
    throw new Error(`${field} must be an integer`);
  }
  return input;
}

function requireBoolean(input: unknown, field: string): boolean {
  if (typeof input !== "boolean") {
    throw new Error(`${field} must be boolean`);
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

function requireExactFields(
  input: Record<string, unknown>,
  allowed: readonly string[],
  field: string,
): void {
  const allowedSet = new Set(allowed);
  for (const key of allowedSet) {
    if (!(key in input)) {
      throw new Error(`${field}.${key} is required`);
    }
  }
  for (const key of Object.keys(input)) {
    if (!allowedSet.has(key)) {
      throw new Error(`${field}.${key} is not supported`);
    }
  }
}

export const memoryListFixtureResponse = parseMemoryListResponse(memoryListFixtureContract);
