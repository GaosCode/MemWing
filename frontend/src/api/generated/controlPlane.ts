import {
  parseMemoryListResponse,
  type MemoryListResponseDto,
} from "./memoryList";
import {
  requireBoolean,
  requireExactFields,
  requireInteger,
  requireOptionalText,
  requireRecord,
  requireText,
  requireTextArray,
} from "./schema";
import type {
  ControlGraphLinkDto,
  ControlIntegrationDto,
  ControlIntegrationsResponseDto,
  ControlJobDto,
  ControlMaintenanceDto,
  ControlMutationResponseDto,
  ControlPageDetailDto,
  ControlPageDto,
  ControlPageListResponseDto,
  ControlPageTopicDto,
  ControlPageVersionDto,
  ControlPushCandidateDto,
  ControlResolvedScopeDto,
  ControlScopeDirectoryItemDto,
  ControlScopeDirectoryResponseDto,
  ControlScopeGroupDto,
  ControlScopeParams,
  ControlScopeProjectDto,
  ControlScopeResolveResponseDto,
  ControlScopeThreadDto,
  ControlSettingsDto,
  ControlSourceEventDetailDto,
  ControlSourceEventDto,
  ControlSourceEventListResponseDto,
  MemoryDetailDto,
} from "./controlPlaneTypes";

export type { MemoryListItemDto, MemoryListResponseDto } from "./memoryList";
export type {
  ControlErrorDto,
  ControlGraphLinkDto,
  ControlIntegrationDto,
  ControlIntegrationsResponseDto,
  ControlJobDto,
  ControlMaintenanceDto,
  ControlMutationResponseDto,
  ControlPageDetailDto,
  ControlPageDto,
  ControlPageListResponseDto,
  ControlPageTopicDto,
  ControlPageVersionDto,
  ControlPushCandidateDto,
  ControlResolvedScopeDto,
  ControlScopeDirectoryItemDto,
  ControlScopeDirectoryResponseDto,
  ControlScopeGroupDto,
  ControlScopeParams,
  ControlScopeProjectDto,
  ControlScopeResolveResponseDto,
  ControlScopeThreadDto,
  ControlSettingsDto,
  ControlSourceEventDetailDto,
  ControlSourceEventDto,
  ControlSourceEventListResponseDto,
  MemoryDetailDto,
  MemoryLifecycleAction,
} from "./controlPlaneTypes";

export function parseControlMemoryListResponse(input: unknown): MemoryListResponseDto {
  return parseMemoryListResponse(input);
}

export function parseMemoryDetail(input: unknown): MemoryDetailDto {
  const object = requireRecord(input, "memory detail");
  requireExactFields(
    object,
    ["item", "content", "source_event_ids", "memory_item_ids", "graph_links", "audit_refs", "trace_id"],
    "memory detail",
  );
  const item = parseMemoryListResponse({
    items: [object.item],
    next_cursor: null,
    trace_id: object.trace_id,
  }).items[0];
  const graphLinks = object.graph_links;
  if (!Array.isArray(graphLinks)) {
    throw new Error("graph_links must be an array");
  }
  return {
    item,
    content: requireText(object.content, "content"),
    source_event_ids: requireTextArray(object.source_event_ids, "source_event_ids"),
    memory_item_ids: requireTextArray(object.memory_item_ids, "memory_item_ids"),
    graph_links: graphLinks.map(parseGraphLink),
    audit_refs: requireTextArray(object.audit_refs, "audit_refs"),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

export function parseMemoryDetailMutation(input: unknown): ControlMutationResponseDto<MemoryDetailDto> {
  return parseMutationResponse(input, parseMemoryDetail);
}

export function parseControlPageList(input: unknown): ControlPageListResponseDto {
  const object = requireRecord(input, "control page list");
  requireExactFields(object, ["items", "next_cursor", "trace_id"], "control page list");
  const items = object.items;
  if (!Array.isArray(items)) {
    throw new Error("items must be an array");
  }
  return {
    items: items.map(parseControlPage),
    next_cursor: requireOptionalText(object.next_cursor, "next_cursor"),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

export function parseControlPageDetail(input: unknown): ControlPageDetailDto {
  const object = requireRecord(input, "control page detail");
  requireExactFields(object, ["page", "versions", "audit_refs", "trace_id"], "control page detail");
  const versions = object.versions;
  if (!Array.isArray(versions)) {
    throw new Error("versions must be an array");
  }
  return {
    page: parseControlPage(object.page),
    versions: versions.map(parseControlPageVersion),
    audit_refs: requireTextArray(object.audit_refs, "audit_refs"),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

export function parseControlPageDetailMutation(input: unknown): ControlMutationResponseDto<ControlPageDetailDto> {
  return parseMutationResponse(input, parseControlPageDetail);
}

export function parseControlSourceEventList(input: unknown): ControlSourceEventListResponseDto {
  const object = requireRecord(input, "control source event list");
  requireExactFields(object, ["items", "next_cursor", "trace_id"], "control source event list");
  const items = object.items;
  if (!Array.isArray(items)) {
    throw new Error("source event items must be an array");
  }
  return {
    items: items.map(parseControlSourceEvent),
    next_cursor: requireOptionalText(object.next_cursor, "next_cursor"),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

export function parseControlSourceEventDetail(input: unknown): ControlSourceEventDetailDto {
  const object = requireRecord(input, "control source event detail");
  requireExactFields(object, ["source_event", "memory_item_ids", "audit_refs", "trace_id"], "control source event detail");
  return {
    source_event: parseControlSourceEvent(object.source_event),
    memory_item_ids: requireTextArray(object.memory_item_ids, "memory_item_ids"),
    audit_refs: requireTextArray(object.audit_refs, "audit_refs"),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

export function parseControlMaintenance(input: unknown): ControlMaintenanceDto {
  const object = requireRecord(input, "control maintenance");
  requireExactFields(
    object,
    [
      "forgetting_review_count",
      "pending_push_count",
      "job_count",
      "warning_count",
      "jobs",
      "push_candidates",
      "jobs_next_cursor",
      "push_candidates_next_cursor",
      "next_cursor",
      "trace_id",
    ],
    "control maintenance",
  );
  const jobs = object.jobs;
  const pushCandidates = object.push_candidates;
  if (!Array.isArray(jobs) || !Array.isArray(pushCandidates)) {
    throw new Error("maintenance jobs and push_candidates must be arrays");
  }
  return {
    forgetting_review_count: requireInteger(object.forgetting_review_count, "forgetting_review_count"),
    pending_push_count: requireInteger(object.pending_push_count, "pending_push_count"),
    job_count: requireInteger(object.job_count, "job_count"),
    warning_count: requireInteger(object.warning_count, "warning_count"),
    jobs: jobs.map(parseControlJob),
    push_candidates: pushCandidates.map(parsePushCandidate),
    jobs_next_cursor: requireOptionalText(object.jobs_next_cursor, "jobs_next_cursor"),
    push_candidates_next_cursor: requireOptionalText(object.push_candidates_next_cursor, "push_candidates_next_cursor"),
    next_cursor: requireOptionalText(object.next_cursor, "next_cursor"),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

export function parseControlMaintenanceMutation(input: unknown): ControlMutationResponseDto<ControlMaintenanceDto> {
  return parseMutationResponse(input, parseControlMaintenance);
}

export function parseControlPushCandidateMutation(input: unknown): ControlMutationResponseDto<ControlPushCandidateDto> {
  return parseMutationResponse(input, parsePushCandidate);
}

export function parseControlSettings(input: unknown): ControlSettingsDto {
  const object = requireRecord(input, "control settings");
  requireExactFields(
    object,
    [
      "project_memory_space_id",
      "safe_mode_enabled",
      "shared_group_id",
      "settings_mutation_supported",
      "trace_id",
    ],
    "control settings",
  );
  return {
    project_memory_space_id: requireText(object.project_memory_space_id, "project_memory_space_id"),
    safe_mode_enabled: requireBoolean(object.safe_mode_enabled, "safe_mode_enabled"),
    shared_group_id: requireOptionalText(object.shared_group_id, "shared_group_id"),
    settings_mutation_supported: requireBoolean(object.settings_mutation_supported, "settings_mutation_supported"),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

export function parseControlScopeDirectory(input: unknown): ControlScopeDirectoryResponseDto {
  const object = requireRecord(input, "control scope directory");
  requireExactFields(object, ["items", "next_cursor", "trace_id"], "control scope directory");
  const items = object.items;
  if (!Array.isArray(items)) {
    throw new Error("items must be an array");
  }
  return {
    items: items.map(parseControlScopeDirectoryItem),
    next_cursor: requireOptionalText(object.next_cursor, "next_cursor"),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

export function parseControlScopeResolve(input: unknown): ControlScopeResolveResponseDto {
  const object = requireRecord(input, "control scope resolve");
  requireExactFields(object, ["requested_scope", "effective_scope", "project", "trace_id"], "control scope resolve");
  return {
    requested_scope: parseControlScopeParams(object.requested_scope),
    effective_scope: parseControlResolvedScope(object.effective_scope),
    project: parseControlScopeProject(object.project),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

function parseControlScopeDirectoryItem(input: unknown): ControlScopeDirectoryItemDto {
  const object = requireRecord(input, "control scope directory item");
  requireExactFields(
    object,
    [
      "project_memory_space_id",
      "name",
      "kind",
      "default_safe_mode_enabled",
      "memory_count",
      "source_event_count",
      "page_count",
      "updated_at",
      "groups",
    ],
    "control scope directory item",
  );
  const groups = object.groups;
  if (!Array.isArray(groups)) {
    throw new Error("groups must be an array");
  }
  return {
    project_memory_space_id: requireText(object.project_memory_space_id, "project_memory_space_id"),
    name: requireText(object.name, "name"),
    kind: requireText(object.kind, "kind"),
    default_safe_mode_enabled: requireBoolean(object.default_safe_mode_enabled, "default_safe_mode_enabled"),
    memory_count: requireInteger(object.memory_count, "memory_count"),
    source_event_count: requireInteger(object.source_event_count, "source_event_count"),
    page_count: requireInteger(object.page_count, "page_count"),
    updated_at: requireOptionalText(object.updated_at, "updated_at"),
    groups: groups.map(parseControlScopeGroup),
  };
}

function parseControlScopeGroup(input: unknown): ControlScopeGroupDto {
  const object = requireRecord(input, "control scope group");
  requireExactFields(
    object,
    ["group_id", "safe_mode_enabled", "shared_group_id", "memory_count", "source_event_count", "threads"],
    "control scope group",
  );
  const threads = object.threads;
  if (!Array.isArray(threads)) {
    throw new Error("threads must be an array");
  }
  return {
    group_id: requireText(object.group_id, "group_id"),
    safe_mode_enabled: requireBoolean(object.safe_mode_enabled, "safe_mode_enabled"),
    shared_group_id: requireOptionalText(object.shared_group_id, "shared_group_id"),
    memory_count: requireInteger(object.memory_count, "memory_count"),
    source_event_count: requireInteger(object.source_event_count, "source_event_count"),
    threads: threads.map(parseControlScopeThread),
  };
}

function parseControlScopeThread(input: unknown): ControlScopeThreadDto {
  const object = requireRecord(input, "control scope thread");
  requireExactFields(object, ["thread_id", "memory_count", "source_event_count", "updated_at"], "control scope thread");
  return {
    thread_id: requireText(object.thread_id, "thread_id"),
    memory_count: requireInteger(object.memory_count, "memory_count"),
    source_event_count: requireInteger(object.source_event_count, "source_event_count"),
    updated_at: requireOptionalText(object.updated_at, "updated_at"),
  };
}

function parseControlScopeParams(input: unknown): ControlScopeParams {
  const object = requireRecord(input, "control scope params");
  requireExactFields(object, ["project_memory_space_id", "group_id", "thread_id", "shared_group_id"], "control scope params");
  return {
    project_memory_space_id: requireText(object.project_memory_space_id, "project_memory_space_id"),
    group_id: requireOptionalText(object.group_id, "group_id") ?? undefined,
    thread_id: requireOptionalText(object.thread_id, "thread_id") ?? undefined,
    shared_group_id: requireOptionalText(object.shared_group_id, "shared_group_id") ?? undefined,
  };
}

function parseControlResolvedScope(input: unknown): ControlResolvedScopeDto {
  const object = requireRecord(input, "control resolved scope");
  requireExactFields(
    object,
    ["project_memory_space_id", "group_ids", "thread_id", "shared_group_id", "safe_mode_enabled", "cross_group_allowed"],
    "control resolved scope",
  );
  return {
    project_memory_space_id: requireText(object.project_memory_space_id, "project_memory_space_id"),
    group_ids: object.group_ids === null ? null : requireTextArray(object.group_ids, "group_ids"),
    thread_id: requireOptionalText(object.thread_id, "thread_id"),
    shared_group_id: requireOptionalText(object.shared_group_id, "shared_group_id"),
    safe_mode_enabled: requireBoolean(object.safe_mode_enabled, "safe_mode_enabled"),
    cross_group_allowed: requireBoolean(object.cross_group_allowed, "cross_group_allowed"),
  };
}

function parseControlScopeProject(input: unknown): ControlScopeProjectDto {
  const object = requireRecord(input, "control scope project");
  requireExactFields(object, ["project_memory_space_id", "name", "kind"], "control scope project");
  return {
    project_memory_space_id: requireText(object.project_memory_space_id, "project_memory_space_id"),
    name: requireText(object.name, "name"),
    kind: requireText(object.kind, "kind"),
  };
}

export function parseControlIntegrations(input: unknown): ControlIntegrationsResponseDto {
  const object = requireRecord(input, "control integrations");
  requireExactFields(object, ["items", "trace_id"], "control integrations");
  const items = object.items;
  if (!Array.isArray(items)) {
    throw new Error("items must be an array");
  }
  return {
    items: items.map(parseControlIntegration),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

function parseMutationResponse<T>(
  input: unknown,
  parseItem: (value: unknown) => T,
): ControlMutationResponseDto<T> {
  const object = requireRecord(input, "mutation response");
  requireExactFields(object, ["ok", "item", "trace_id"], "mutation response");
  if (object.ok !== true) {
    throw new Error("mutation response ok must be true");
  }
  return {
    ok: true,
    item: parseItem(object.item),
    trace_id: requireText(object.trace_id, "trace_id"),
  };
}

function parseGraphLink(input: unknown): ControlGraphLinkDto {
  const object = requireRecord(input, "graph link");
  requireExactFields(object, ["id", "backend", "backend_object_type", "backend_object_id", "link_type"], "graph link");
  return {
    id: requireText(object.id, "id"),
    backend: requireText(object.backend, "backend"),
    backend_object_type: requireText(object.backend_object_type, "backend_object_type"),
    backend_object_id: requireText(object.backend_object_id, "backend_object_id"),
    link_type: requireText(object.link_type, "link_type"),
  };
}

function parseControlPage(input: unknown): ControlPageDto {
  const object = requireRecord(input, "control page");
  requireExactFields(
    object,
    [
      "id",
      "project_memory_space_id",
      "group_id",
      "thread_id",
      "shared_group_id",
      "scope_type",
      "scope_id",
      "title",
      "brief",
      "topics",
      "open_questions",
      "next_steps",
      "source_event_ids",
      "linked_memory_item_ids",
      "version",
      "needs_rebuild",
      "graph_backend_raw_retained",
      "warning_count",
      "updated_at",
    ],
    "control page",
  );
  const topics = object.topics;
  if (!Array.isArray(topics)) {
    throw new Error("topics must be an array");
  }
  return {
    id: requireText(object.id, "id"),
    project_memory_space_id: requireText(object.project_memory_space_id, "project_memory_space_id"),
    group_id: requireOptionalText(object.group_id, "group_id"),
    thread_id: requireOptionalText(object.thread_id, "thread_id"),
    shared_group_id: requireOptionalText(object.shared_group_id, "shared_group_id"),
    scope_type: requireText(object.scope_type, "scope_type"),
    scope_id: requireText(object.scope_id, "scope_id"),
    title: requireText(object.title, "title"),
    brief: requireText(object.brief, "brief"),
    topics: topics.map(parseControlPageTopic),
    open_questions: requireTextArray(object.open_questions, "open_questions"),
    next_steps: requireTextArray(object.next_steps, "next_steps"),
    source_event_ids: requireTextArray(object.source_event_ids, "source_event_ids"),
    linked_memory_item_ids: requireTextArray(object.linked_memory_item_ids, "linked_memory_item_ids"),
    version: requireInteger(object.version, "version"),
    needs_rebuild: requireBoolean(object.needs_rebuild, "needs_rebuild"),
    graph_backend_raw_retained: requireBoolean(object.graph_backend_raw_retained, "graph_backend_raw_retained"),
    warning_count: requireInteger(object.warning_count, "warning_count"),
    updated_at: requireText(object.updated_at, "updated_at"),
  };
}

function parseControlPageTopic(input: unknown): ControlPageTopicDto {
  const object = requireRecord(input, "control page topic");
  requireExactFields(object, ["title", "summary", "source_event_ids", "linked_memory_item_ids"], "control page topic");
  return {
    title: requireText(object.title, "title"),
    summary: requireText(object.summary, "summary"),
    source_event_ids: requireTextArray(object.source_event_ids, "source_event_ids"),
    linked_memory_item_ids: requireTextArray(object.linked_memory_item_ids, "linked_memory_item_ids"),
  };
}

function parseControlPageVersion(input: unknown): ControlPageVersionDto {
  const object = requireRecord(input, "control page version");
  requireExactFields(
    object,
    [
      "id",
      "page_id",
      "version",
      "title",
      "brief",
      "topics",
      "open_questions",
      "next_steps",
      "source_event_ids",
      "linked_memory_item_ids",
      "changed_by",
      "change_reason",
      "created_at",
    ],
    "control page version",
  );
  const topics = object.topics;
  if (!Array.isArray(topics)) {
    throw new Error("version topics must be an array");
  }
  return {
    id: requireText(object.id, "id"),
    page_id: requireText(object.page_id, "page_id"),
    version: requireInteger(object.version, "version"),
    title: requireText(object.title, "title"),
    brief: requireText(object.brief, "brief"),
    topics: topics.map(parseControlPageTopic),
    open_questions: requireTextArray(object.open_questions, "open_questions"),
    next_steps: requireTextArray(object.next_steps, "next_steps"),
    source_event_ids: requireTextArray(object.source_event_ids, "source_event_ids"),
    linked_memory_item_ids: requireTextArray(object.linked_memory_item_ids, "linked_memory_item_ids"),
    changed_by: requireText(object.changed_by, "changed_by"),
    change_reason: requireText(object.change_reason, "change_reason"),
    created_at: requireText(object.created_at, "created_at"),
  };
}

function parseControlJob(input: unknown): ControlJobDto {
  const object = requireRecord(input, "control job");
  requireExactFields(
    object,
    ["id", "kind", "status", "attempts", "max_attempts", "next_run_at", "last_error", "dead_letter_reason", "retryable"],
    "control job",
  );
  return {
    id: requireText(object.id, "id"),
    kind: requireText(object.kind, "kind"),
    status: requireText(object.status, "status"),
    attempts: requireInteger(object.attempts, "attempts"),
    max_attempts: requireInteger(object.max_attempts, "max_attempts"),
    next_run_at: requireText(object.next_run_at, "next_run_at"),
    last_error: requireOptionalText(object.last_error, "last_error"),
    dead_letter_reason: requireOptionalText(object.dead_letter_reason, "dead_letter_reason"),
    retryable: requireBoolean(object.retryable, "retryable"),
  };
}

function parseControlSourceEvent(input: unknown): ControlSourceEventDto {
  const object = requireRecord(input, "control source event");
  requireExactFields(
    object,
    [
      "id",
      "project_memory_space_id",
      "group_id",
      "thread_id",
      "source_type",
      "content_preview",
      "source_url",
      "purged",
      "purge_level",
      "graph_backend_raw_retained",
      "event_time",
      "created_at",
    ],
    "control source event",
  );
  return {
    id: requireText(object.id, "id"),
    project_memory_space_id: requireText(object.project_memory_space_id, "project_memory_space_id"),
    group_id: requireOptionalText(object.group_id, "group_id"),
    thread_id: requireOptionalText(object.thread_id, "thread_id"),
    source_type: requireText(object.source_type, "source_type"),
    content_preview: requireText(object.content_preview, "content_preview"),
    source_url: requireOptionalText(object.source_url, "source_url"),
    purged: requireBoolean(object.purged, "purged"),
    purge_level: requireText(object.purge_level, "purge_level"),
    graph_backend_raw_retained: requireBoolean(object.graph_backend_raw_retained, "graph_backend_raw_retained"),
    event_time: requireText(object.event_time, "event_time"),
    created_at: requireText(object.created_at, "created_at"),
  };
}

function parseControlIntegration(input: unknown): ControlIntegrationDto {
  const object = requireRecord(input, "control integration");
  requireExactFields(object, ["name", "configured", "writable"], "control integration");
  return {
    name: requireText(object.name, "name"),
    configured: requireBoolean(object.configured, "configured"),
    writable: requireBoolean(object.writable, "writable"),
  };
}

function parsePushCandidate(input: unknown): ControlPushCandidateDto {
  const object = requireRecord(input, "push candidate");
  requireExactFields(
    object,
    ["id", "type", "title", "status", "priority", "memory_item_ids", "source_event_ids", "trigger_reason", "created_at"],
    "push candidate",
  );
  return {
    id: requireText(object.id, "id"),
    type: requireText(object.type, "type"),
    title: requireText(object.title, "title"),
    status: requireText(object.status, "status"),
    priority: requireInteger(object.priority, "priority"),
    memory_item_ids: requireTextArray(object.memory_item_ids, "memory_item_ids"),
    source_event_ids: requireTextArray(object.source_event_ids, "source_event_ids"),
    trigger_reason: requireText(object.trigger_reason, "trigger_reason"),
    created_at: requireText(object.created_at, "created_at"),
  };
}
