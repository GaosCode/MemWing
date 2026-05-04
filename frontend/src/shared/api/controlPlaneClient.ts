import {
  parseControlIntegrations,
  parseControlMaintenance,
  parseControlMaintenanceMutation,
  parseControlMemoryListResponse,
  parseControlPageDetail,
  parseControlPageDetailMutation,
  parseControlPageList,
  parseControlPushCandidateMutation,
  parseControlSettings,
  parseControlSourceEventDetail,
  parseControlSourceEventList,
  parseMemoryDetail,
  parseMemoryDetailMutation,
  type ControlIntegrationsResponseDto,
  type ControlMaintenanceDto,
  type ControlPageDetailDto,
  type ControlPageListResponseDto,
  type ControlPushCandidateDto,
  type ControlScopeParams,
  type ControlSettingsDto,
  type ControlSourceEventDetailDto,
  type ControlSourceEventListResponseDto,
  type MemoryDetailDto,
  type MemoryLifecycleAction,
  type MemoryListResponseDto,
} from "../../api/generated/controlPlane";
import {
  requireBoolean,
  requireOptionalText,
  requireRecord,
  requireText,
} from "../../api/generated/schema";

const API_BASE = (import.meta.env.VITE_MEMWING_API_BASE ?? "").replace(/\/$/, "");
const ACTOR_ID = import.meta.env.VITE_MEMWING_ACTOR_ID ?? "user_001";

export type MemoryEditInput = {
  title: string;
  content: string;
  summary: string | null;
};

export type PageEditInput = {
  title: string;
  brief: string;
};

export type ManualMemoryInput = {
  title: string;
  content: string;
  sourceUrl: string | null;
  reason: string;
};

export type RememberEventResponseDto = {
  source_event_id: string;
  accepted: boolean;
  trace_id: string;
  duplicate_of: string | null;
};

export async function listControlMemories(scope: ControlScopeParams): Promise<MemoryListResponseDto> {
  return parseControlMemoryListResponse(await getJson("/v1/control/memories", scope));
}

export async function getControlMemory(scope: ControlScopeParams, memoryId: string): Promise<MemoryDetailDto> {
  return parseMemoryDetail(await getJson(`/v1/control/memories/${memoryId}`, scope));
}

export async function mutateMemoryLifecycle(
  scope: ControlScopeParams,
  memoryId: string,
  action: MemoryLifecycleAction,
  reason: string,
): Promise<MemoryDetailDto> {
  const body = mutationEnvelope(reason, `${action}:${memoryId}`);
  return parseMemoryDetailMutation(await postJson(`/v1/memory/${memoryId}/${action}`, scope, body)).item;
}

export async function editMemory(
  scope: ControlScopeParams,
  memoryId: string,
  input: MemoryEditInput,
  reason: string,
): Promise<MemoryDetailDto> {
  const body = {
    ...mutationEnvelope(reason, `edit:${memoryId}`),
    title: input.title,
    content: input.content,
    summary: input.summary,
  };
  return parseMemoryDetailMutation(await patchJson(`/v1/memory/${memoryId}`, scope, body)).item;
}

export async function createManualMemory(
  scope: ControlScopeParams,
  input: ManualMemoryInput,
): Promise<RememberEventResponseDto> {
  const body = {
    ...mutationEnvelope(input.reason, `manual-memory:${scope.project_memory_space_id}`),
    title: input.title,
    content: input.content,
    source_url: input.sourceUrl,
  };
  return parseRememberEventResponse(await postJson("/v1/control/memories/manual", scope, body));
}

export async function listControlPages(scope: ControlScopeParams): Promise<ControlPageListResponseDto> {
  return parseControlPageList(await getJson("/v1/control/pages", scope));
}

export async function getControlPage(scope: ControlScopeParams, pageId: string): Promise<ControlPageDetailDto> {
  return parseControlPageDetail(await getJson(`/v1/control/pages/${pageId}`, scope));
}

export async function listControlSourceEvents(scope: ControlScopeParams): Promise<ControlSourceEventListResponseDto> {
  return parseControlSourceEventList(await getJson("/v1/control/source-events", scope));
}

export async function getControlSourceEvent(
  scope: ControlScopeParams,
  sourceEventId: string,
): Promise<ControlSourceEventDetailDto> {
  return parseControlSourceEventDetail(await getJson(`/v1/control/source-events/${sourceEventId}`, scope));
}

export async function editControlPage(
  scope: ControlScopeParams,
  pageId: string,
  input: PageEditInput,
  reason: string,
): Promise<ControlPageDetailDto> {
  const body = {
    ...mutationEnvelope(reason, `edit-page:${pageId}`),
    title: input.title,
    brief: input.brief,
  };
  return parseControlPageDetailMutation(await patchJson(`/v1/control/pages/${pageId}`, scope, body)).item;
}

export async function rebuildControlPage(
  scope: ControlScopeParams,
  pageId: string,
  reason: string,
): Promise<ControlPageDetailDto> {
  const body = mutationEnvelope(reason, `rebuild-page:${pageId}`);
  return parseControlPageDetailMutation(await postJson(`/v1/control/pages/${pageId}/rebuild`, scope, body)).item;
}

export async function restoreControlPageVersion(
  scope: ControlScopeParams,
  pageId: string,
  version: number,
  reason: string,
): Promise<ControlPageDetailDto> {
  const body = {
    ...mutationEnvelope(reason, `restore-page:${pageId}:${version}`),
    version,
  };
  return parseControlPageDetailMutation(await postJson(`/v1/control/pages/${pageId}/restore-version`, scope, body)).item;
}

export async function getControlMaintenance(scope: ControlScopeParams): Promise<ControlMaintenanceDto> {
  return parseControlMaintenance(await getJson("/v1/control/maintenance", scope));
}

export async function retryControlJob(
  scope: ControlScopeParams,
  jobId: string,
  kind: string,
  reason: string,
): Promise<ControlMaintenanceDto> {
  const body = {
    ...mutationEnvelope(reason, `retry-job:${kind}:${jobId}`),
    kind,
  };
  return parseControlMaintenanceMutation(await postJson(`/v1/control/jobs/${jobId}/retry`, scope, body)).item;
}

export async function approvePushCandidate(
  scope: ControlScopeParams,
  candidateId: string,
  reason: string,
): Promise<ControlPushCandidateDto> {
  const body = mutationEnvelope(reason, `approve-push:${candidateId}`);
  return parseControlPushCandidateMutation(await postJson(`/v1/control/push-candidates/${candidateId}/approve`, scope, body)).item;
}

export async function skipPushCandidate(
  scope: ControlScopeParams,
  candidateId: string,
  reason: string,
): Promise<ControlPushCandidateDto> {
  const body = mutationEnvelope(reason, `skip-push:${candidateId}`);
  return parseControlPushCandidateMutation(await postJson(`/v1/control/push-candidates/${candidateId}/skip`, scope, body)).item;
}

export async function sendFeishuPushCandidate(
  scope: ControlScopeParams,
  candidateId: string,
  reason: string,
): Promise<ControlPushCandidateDto> {
  const body = mutationEnvelope(reason, `send-feishu-push:${candidateId}`);
  return parseControlPushCandidateMutation(
    await postJson(`/v1/platforms/feishu/push-candidates/${candidateId}/send`, scope, body),
  ).item;
}

export async function getControlSettings(scope: ControlScopeParams): Promise<ControlSettingsDto> {
  return parseControlSettings(await getJson("/v1/control/settings", scope));
}

export async function getControlIntegrations(): Promise<ControlIntegrationsResponseDto> {
  const response = await fetch(`${API_BASE}/v1/control/integrations`);
  return parseControlIntegrations(await responseJson(response));
}

async function getJson(path: string, scope: ControlScopeParams): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}?${scopeSearchParams(scope).toString()}`);
  return responseJson(response);
}

async function postJson(path: string, scope: ControlScopeParams, body: object): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}?${scopeSearchParams(scope).toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return responseJson(response);
}

async function patchJson(path: string, scope: ControlScopeParams, body: object): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}?${scopeSearchParams(scope).toString()}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return responseJson(response);
}

async function responseJson(response: Response): Promise<unknown> {
  const payload = await response.json();
  if (!response.ok) {
    const message = errorMessage(payload);
    throw new Error(message);
  }
  return payload;
}

function mutationEnvelope(reason: string, idempotencyKeyPrefix: string) {
  const timestamp = Date.now();
  return {
    actor_id: ACTOR_ID,
    reason,
    idempotency_key: `${idempotencyKeyPrefix}:${timestamp}`,
    trace_id: `frontend:${idempotencyKeyPrefix}:${timestamp}`,
  };
}

function scopeSearchParams(scope: ControlScopeParams): URLSearchParams {
  const entries = Object.entries(scope).filter((entry): entry is [string, string] => {
    const value = entry[1];
    return typeof value === "string" && value.trim().length > 0;
  });
  return new URLSearchParams(entries);
}

function parseRememberEventResponse(input: unknown): RememberEventResponseDto {
  const object = requireRecord(input, "remember event response");
  return {
    source_event_id: requireText(object.source_event_id, "source_event_id"),
    accepted: requireBoolean(object.accepted, "accepted"),
    trace_id: requireText(object.trace_id, "trace_id"),
    duplicate_of: "duplicate_of" in object ? requireOptionalText(object.duplicate_of, "duplicate_of") : null,
  };
}

function errorMessage(payload: unknown): string {
  if (payload !== null && typeof payload === "object" && "message" in payload) {
    const message = (payload as { message?: unknown }).message;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }
  }
  return "MemWing API request failed";
}
