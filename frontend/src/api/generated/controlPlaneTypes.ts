import type { MemoryListItemDto } from "./memoryList";

export type ControlGraphLinkDto = {
  id: string;
  backend: string;
  backend_object_type: string;
  backend_object_id: string;
  link_type: string;
};

export type MemoryDetailDto = {
  item: MemoryListItemDto;
  content: string;
  source_event_ids: string[];
  memory_item_ids: string[];
  graph_links: ControlGraphLinkDto[];
  audit_refs: string[];
  trace_id: string;
};

export type ControlMutationResponseDto<T> = {
  ok: true;
  item: T;
  trace_id: string;
};

export type ControlErrorDto = {
  ok: false;
  code: string;
  message: string;
  trace_id?: string;
};

export type ControlPageTopicDto = {
  title: string;
  summary: string;
  source_event_ids: string[];
  linked_memory_item_ids: string[];
};

export type ControlPageDto = {
  id: string;
  project_memory_space_id: string;
  group_id: string | null;
  thread_id: string | null;
  shared_group_id: string | null;
  scope_type: string;
  scope_id: string;
  title: string;
  brief: string;
  topics: ControlPageTopicDto[];
  open_questions: string[];
  next_steps: string[];
  source_event_ids: string[];
  linked_memory_item_ids: string[];
  version: number;
  needs_rebuild: boolean;
  graph_backend_raw_retained: boolean;
  warning_count: number;
  updated_at: string;
};

export type ControlPageVersionDto = {
  id: string;
  page_id: string;
  version: number;
  title: string;
  brief: string;
  topics: ControlPageTopicDto[];
  open_questions: string[];
  next_steps: string[];
  source_event_ids: string[];
  linked_memory_item_ids: string[];
  changed_by: string;
  change_reason: string;
  created_at: string;
};

export type ControlPageListResponseDto = {
  items: ControlPageDto[];
  next_cursor: string | null;
  trace_id: string;
};

export type ControlPageDetailDto = {
  page: ControlPageDto;
  versions: ControlPageVersionDto[];
  audit_refs: string[];
  trace_id: string;
};

export type ControlJobDto = {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  max_attempts: number;
  next_run_at: string;
  last_error: string | null;
  dead_letter_reason: string | null;
  retryable: boolean;
};

export type ControlPushCandidateDto = {
  id: string;
  type: string;
  title: string;
  status: string;
  priority: number;
  memory_item_ids: string[];
  source_event_ids: string[];
  trigger_reason: string;
  created_at: string;
};

export type ControlMaintenanceDto = {
  forgetting_review_count: number;
  pending_push_count: number;
  job_count: number;
  warning_count: number;
  jobs: ControlJobDto[];
  push_candidates: ControlPushCandidateDto[];
  jobs_next_cursor: string | null;
  push_candidates_next_cursor: string | null;
  next_cursor: string | null;
  trace_id: string;
};

export type ControlSettingsDto = {
  project_memory_space_id: string;
  safe_mode_enabled: boolean;
  shared_group_id: string | null;
  settings_mutation_supported: boolean;
  trace_id: string;
};

export type ControlIntegrationDto = {
  name: string;
  configured: boolean;
  writable: boolean;
};

export type ControlIntegrationsResponseDto = {
  items: ControlIntegrationDto[];
  trace_id: string;
};

export type ControlScopeParams = {
  project_memory_space_id: string;
  group_id?: string;
  thread_id?: string;
  shared_group_id?: string;
};

export type MemoryLifecycleAction =
  | "confirm"
  | "review"
  | "pin"
  | "unpin"
  | "archive"
  | "unarchive"
  | "hide"
  | "unhide"
  | "remove";
