import { readFileSync } from "node:fs";
import type { IncomingMessage } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
type JsonObject = { [key: string]: JsonValue };
type MemoryFixtureItem = JsonObject & {
  id: string;
  title: string;
  summary: string | null;
  source_event_ids: string[];
};
type MemoryListFixture = {
  items: MemoryFixtureItem[];
  next_cursor: string | null;
  trace_id: string;
};

const configDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(configDir, "..");
const memoryListFixturePath = join(repoRoot, "shared_contracts", "memory_list.fixture.json");
const mockTime = "2026-04-27T11:32:00+00:00";

export function memwingMockApiPlugin(): Plugin {
  const memoryList = readMemoryListFixture();
  const firstMemory = memoryList.items[0];
  const page = mockPage(firstMemory);
  const pageDetail = mockPageDetail(page);
  const maintenance = mockMaintenance(firstMemory);
  const settings = {
    project_memory_space_id: "project_001",
    safe_mode_enabled: true,
    shared_group_id: null,
    settings_mutation_supported: false,
    trace_id: "mock_settings",
  };
  const integrations = {
    items: [{ name: "feishu", configured: false, writable: false }],
    trace_id: "mock_integrations",
  };
  const sourceEvent = {
    id: firstMemory.source_event_ids[0] ?? "source_mock",
    project_memory_space_id: "project_001",
    group_id: firstMemory.group_id ?? null,
    thread_id: firstMemory.thread_id ?? null,
    source_type: "mock",
    content_preview: firstMemory.summary ?? firstMemory.title,
    source_url: null,
    purged: false,
    purge_level: "none",
    graph_backend_raw_retained: false,
    event_time: mockTime,
    created_at: mockTime,
  };

  return {
    name: "memwing-local-mock-api",
    configureServer(server) {
      server.config.logger.info("Mock /v1 on.");
      server.middlewares.use((request, response, next) => {
        if (request.url === undefined || request.method === undefined) {
          next();
          return;
        }

        const url = new URL(request.url, "http://memwing.local");
        const path = url.pathname;
        if (!path.startsWith("/v1/")) {
          next();
          return;
        }

        void readRequestJson(request)
          .then((payload) => {
            const memoryId = segment(path, 3);
            const pushCandidateId = segment(path, 4);
            const includeBenchmarkScopes = url.searchParams.get("include_benchmark") === "true";
            const body = routeMockApi({
              method: request.method ?? "GET",
              path,
              payload,
              memoryList,
              memoryId,
              pushCandidateId,
              page,
              pageDetail,
              maintenance,
              settings,
              integrations,
              sourceEvent,
              includeBenchmarkScopes,
            });
            sendJson(response, body.status, body.payload);
          })
          .catch(next);
      });
    },
  };
}

function routeMockApi(input: {
  method: string;
  path: string;
  payload: JsonObject;
  memoryList: MemoryListFixture;
  memoryId: string;
  pushCandidateId: string;
  page: JsonObject;
  pageDetail: JsonObject;
  maintenance: JsonObject;
  settings: JsonObject;
  integrations: JsonObject;
  sourceEvent: JsonObject;
  includeBenchmarkScopes: boolean;
}): { status: number; payload: JsonObject } {
  const {
    method,
    path,
    payload,
    memoryList,
    memoryId,
    pushCandidateId,
    page,
    pageDetail,
    maintenance,
    settings,
    integrations,
    sourceEvent,
    includeBenchmarkScopes,
  } = input;

  if (method === "POST" && path === "/v1/control/memories/manual") {
    const memory = mockManualMemory(payload);
    memoryList.items.unshift(memory);
    return {
      status: 202,
      payload: {
        source_event_id: memory.source_event_ids[0],
        accepted: true,
        duplicate_of: null,
        trace_id: "mock_manual_memory",
      },
    };
  }
  if (method === "GET" && path === "/v1/control/memories") {
    return ok(memoryList);
  }
  if (method === "GET" && path.startsWith("/v1/control/memories/")) {
    return ok(mockMemoryDetail(memoryList, memoryId));
  }
  if (method === "GET" && path === "/v1/control/maintenance") {
    return ok(maintenance);
  }
  if (method === "GET" && path === "/v1/control/pages") {
    return ok({ items: [page], next_cursor: null, trace_id: "mock_pages" });
  }
  if (method === "GET" && path.startsWith("/v1/control/pages/")) {
    return ok(pageDetail);
  }
  if (method === "GET" && path.startsWith("/v1/control/source-events/")) {
    return ok({
      source_event: sourceEvent,
      memory_item_ids: memoryList.items.map((item) => item.id),
      audit_refs: ["mock_audit_source"],
      trace_id: "mock_source_event_detail",
    });
  }
  if (method === "GET" && path === "/v1/control/settings") {
    return ok(settings);
  }
  if (method === "GET" && path === "/v1/control/scopes") {
    return ok(mockScopeDirectory(memoryList, includeBenchmarkScopes));
  }
  if (method === "GET" && path === "/v1/control/scopes/resolve") {
    return ok({
      requested_scope: {
        project_memory_space_id: "project_001",
        group_id: "group_product",
        thread_id: "thread_planning",
        shared_group_id: null,
      },
      effective_scope: {
        project_memory_space_id: "project_001",
        group_ids: null,
        thread_id: "thread_planning",
        shared_group_id: null,
        safe_mode_enabled: false,
        cross_group_allowed: true,
      },
      project: {
        project_memory_space_id: "project_001",
        name: "Mock Project",
        kind: "project",
      },
      trace_id: "mock_scope_resolve",
    });
  }
  if (method === "GET" && path === "/v1/control/integrations") {
    return ok(integrations);
  }
  if ((method === "PATCH" || method === "POST") && path.startsWith("/v1/memory/")) {
    return mutation(mockMemoryDetail(memoryList, memoryId));
  }
  if ((method === "PATCH" || method === "POST") && path.startsWith("/v1/control/pages/")) {
    return mutation(pageDetail);
  }
  if (method === "POST" && path.startsWith("/v1/control/jobs/")) {
    return mutation(maintenance);
  }
  if (method === "POST" && path.startsWith("/v1/control/push-candidates/")) {
    return mutation(mockPushCandidate(pushCandidateId));
  }
  if (method === "POST" && path.startsWith("/v1/platforms/feishu/push-candidates/")) {
    return mutation(mockPushCandidate(pushCandidateId));
  }

  return {
    status: 404,
    payload: {
      ok: false,
      code: "mock_route_not_found",
      message: `No mock route for ${method} ${path}`,
      trace_id: "mock_404",
    },
  };
}

function readMemoryListFixture(): MemoryListFixture {
  return JSON.parse(readFileSync(memoryListFixturePath, "utf8")) as MemoryListFixture;
}

function mockManualMemory(payload: JsonObject): MemoryFixtureItem {
  const nestedPayload = jsonObjectValue(payload.payload);
  const scope = jsonObjectValue(payload.scope);
  const content = textValue(payload.content) ?? textValue(nestedPayload?.content) ?? "Manual memory";
  const title = textValue(payload.title) ?? textValue(nestedPayload?.title) ?? content.split(/\n+/)[0] ?? "Manual memory";
  const reason = textValue(payload.reason) ?? textValue(nestedPayload?.reason) ?? "manual memory submitted from control plane";
  const eventTime = textValue(payload.event_time) ?? new Date().toISOString();
  const suffix = String(Date.now());
  return {
    id: `mock_manual_memory_${suffix}`,
    title,
    summary: content,
    display_type: "note",
    route: "manual",
    status: "candidate",
    group_id: textValue(scope?.group_id),
    thread_id: textValue(scope?.thread_id),
    source_event_ids: [`mock_manual_source_${suffix}`],
    decay_score: 1,
    original_score: 1,
    half_life_days: 90,
    recall_threshold: 0.45,
    curve_state: "retained",
    last_reinforced_at: eventTime,
    next_review_at: null,
    retention_reason: reason,
    flags: ["manual"],
    source_state: "manual",
    graph_backend_raw_retained: false,
    available_actions: ["confirm", "edit", "archive", "hide"],
    warning_count: 0,
    updated_at: eventTime,
  };
}

function mockMemoryDetail(memoryList: MemoryListFixture, memoryId: string): JsonObject {
  const item = memoryList.items.find((candidate) => candidate.id === memoryId) ?? memoryList.items[0];
  return {
    item,
    content: item.summary ?? item.title,
    source_event_ids: [...item.source_event_ids],
    memory_item_ids: [item.id],
    graph_links: [
      {
        id: `mock_graph_${item.id}`,
        backend: "mock",
        backend_object_type: "entity",
        backend_object_id: item.id,
        link_type: "mentions",
      },
    ],
    audit_refs: ["mock_audit_memory"],
    trace_id: "mock_memory_detail",
  };
}

function mockPage(memory: MemoryFixtureItem): JsonObject {
  return {
    id: "mock_page_001",
    project_memory_space_id: "project_001",
    group_id: memory.group_id ?? null,
    thread_id: memory.thread_id ?? null,
    shared_group_id: null,
    scope_type: "thread",
    scope_id: memory.thread_id ?? "thread_mock",
    title: "Mock Project Memory",
    brief: "Local Vite mock data.",
    topics: [
      {
        title: memory.title,
        summary: memory.summary ?? memory.title,
        source_event_ids: [...memory.source_event_ids],
        linked_memory_item_ids: [memory.id],
      },
    ],
    open_questions: ["Connect a real API for live data."],
    next_steps: ["Set VITE_MEMWING_API_PROXY_TARGET."],
    source_event_ids: [...memory.source_event_ids],
    linked_memory_item_ids: [memory.id],
    version: 1,
    needs_rebuild: false,
    graph_backend_raw_retained: false,
    warning_count: 0,
    updated_at: mockTime,
  };
}

function mockPageDetail(page: JsonObject): JsonObject {
  return {
    page,
    versions: [
      {
        id: "mock_page_version_001",
        page_id: page.id,
        version: page.version,
        title: page.title,
        brief: page.brief,
        topics: page.topics,
        open_questions: page.open_questions,
        next_steps: page.next_steps,
        source_event_ids: page.source_event_ids,
        linked_memory_item_ids: page.linked_memory_item_ids,
        changed_by: "mock",
        change_reason: "local mock data",
        created_at: mockTime,
      },
    ],
    audit_refs: ["mock_audit_page"],
    trace_id: "mock_page_detail",
  };
}

function mockMaintenance(memory: MemoryFixtureItem): JsonObject {
  return {
    forgetting_review_count: 0,
    pending_push_count: 1,
    job_count: 1,
    warning_count: 1,
    jobs: [
      {
        id: "mock_job_001",
        kind: "outbox",
        status: "dead_letter",
        attempts: 3,
        max_attempts: 3,
        next_run_at: mockTime,
        last_error: "Local mock backend is active.",
        dead_letter_reason: "mock_only",
        retryable: true,
      },
    ],
    push_candidates: [mockPushCandidate("mock_push_001", memory)],
    jobs_next_cursor: null,
    push_candidates_next_cursor: null,
    next_cursor: null,
    trace_id: "mock_maintenance",
  };
}

function mockScopeDirectory(memoryList: MemoryListFixture, includeBenchmarkScopes: boolean): JsonObject {
  const groups = Array.from(new Set(memoryList.items.map((item) => item.group_id).filter(Boolean)));
  const projectScope = {
    project_memory_space_id: "project_001",
    name: "Mock Project",
    kind: "project",
    default_safe_mode_enabled: false,
    memory_count: memoryList.items.length,
    source_event_count: memoryList.items.length,
    page_count: 1,
    updated_at: mockTime,
    groups: groups.map((groupId) => ({
      group_id: groupId,
      safe_mode_enabled: false,
      shared_group_id: null,
      memory_count: memoryList.items.filter((item) => item.group_id === groupId).length,
      source_event_count: memoryList.items.filter((item) => item.group_id === groupId).length,
      threads: Array.from(new Set(
        memoryList.items
          .filter((item) => item.group_id === groupId)
          .map((item) => item.thread_id)
          .filter(Boolean),
      )).map((threadId) => ({
        thread_id: threadId,
        memory_count: memoryList.items.filter((item) => item.thread_id === threadId).length,
        source_event_count: memoryList.items.filter((item) => item.thread_id === threadId).length,
        updated_at: mockTime,
      })),
    })),
  };
  const benchmarkScope = {
    project_memory_space_id: "benchmark:mock-run:bs001",
    name: "Benchmark benchmark:mock-run:bs001",
    kind: "benchmark",
    default_safe_mode_enabled: false,
    memory_count: 4,
    source_event_count: 13,
    page_count: 1,
    updated_at: mockTime,
    groups: [
      {
        group_id: "benchmark:bs001",
        safe_mode_enabled: true,
        shared_group_id: null,
        memory_count: 4,
        source_event_count: 13,
        threads: [
          {
            thread_id: "benchmark:bs001",
            memory_count: 4,
            source_event_count: 13,
            updated_at: mockTime,
          },
        ],
      },
    ],
  };
  return {
    items: includeBenchmarkScopes ? [benchmarkScope, projectScope] : [projectScope],
    next_cursor: null,
    trace_id: "mock_scopes",
  };
}

function mockPushCandidate(id: string, memory?: MemoryFixtureItem): JsonObject {
  return {
    id: id || "mock_push_001",
    type: "feishu",
    title: memory?.title ?? "Mock push candidate",
    status: "pending",
    priority: 1,
    memory_item_ids: memory === undefined ? [] : [memory.id],
    source_event_ids: memory?.source_event_ids ?? [],
    trigger_reason: "local mock data",
    created_at: mockTime,
  };
}

function ok(payload: JsonObject | MemoryListFixture): { status: number; payload: JsonObject } {
  return { status: 200, payload: payload as JsonObject };
}

function mutation(item: JsonObject): { status: number; payload: JsonObject } {
  return {
    status: 200,
    payload: {
      ok: true,
      item,
      trace_id: "mock_mutation",
    },
  };
}

function segment(path: string, index: number): string {
  return path.split("/")[index] ?? "";
}

function sendJson(response: { statusCode: number; setHeader: (name: string, value: string) => void; end: (body: string) => void }, status: number, payload: JsonObject) {
  response.statusCode = status;
  response.setHeader("Content-Type", "application/json");
  response.end(JSON.stringify(payload));
}

function readRequestJson(request: IncomingMessage): Promise<JsonObject> {
  if (request.method === "GET" || request.method === "HEAD") {
    return Promise.resolve({});
  }
  return new Promise((resolve, reject) => {
    let raw = "";
    request.on("data", (chunk: Buffer | string) => {
      raw += chunk.toString();
    });
    request.on("end", () => {
      if (raw.trim().length === 0) {
        resolve({});
        return;
      }
      const parsed = JSON.parse(raw) as unknown;
      resolve(jsonObjectValue(parsed) ?? {});
    });
    request.on("error", reject);
  });
}

function jsonObjectValue(value: unknown): JsonObject | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as JsonObject;
}

function textValue(value: JsonValue | undefined): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}
