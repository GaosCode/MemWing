"use strict";

const { existsSync } = require("node:fs");
const { spawn } = require("node:child_process");
const pluginPackage = require("../package.json");
const {
  OpenClawToolSchemaError,
  toolParameters,
  validateMemoryIdParams,
  validateProjectContextParams,
  validateSearchParams
} = require("./toolSchemas.js");
const {
  nativeToolParameters,
  validateNativeGetParams,
  validateNativeIndexParams,
  validateNativeSearchParams,
  validateNativeStatusParams
} = require("./nativeSchemas.js");
const { createMemWingHttpClient } = require("./httpClient.js");

const REQUIRED_OBSERVATION_HOOKS = [
  "after_tool_call",
  "agent_end",
  "llm_input",
  "llm_output",
  "session_start",
  "session_end",
  "before_compaction",
  "after_compaction"
];

const OPENCLAW_DELIVERY_HOOK = "reply_dispatch";
const REQUIRED_HOOKS = [...REQUIRED_OBSERVATION_HOOKS, OPENCLAW_DELIVERY_HOOK];

const REQUIRED_TOOLS = [
  "memwing_search_memory",
  "memwing_get_memory",
  "memwing_explain_memory",
  "memwing_search_sources",
  "memwing_get_project_context"
];

const CONTEXT_ENGINE_INFO = {
  id: "memwing",
  name: "MemWing",
  version: pluginPackage.version,
  ownsCompaction: false
};

function register(api, options = {}) {
  assertOpenClawApi(api);
  const client = options.client || createMemWingHttpClient(registrationClientOptions(api, options));
  const config = options.config || api.pluginConfig || {};
  api.registerContextEngine("memwing", () => createContextEngine(api, client, config));

  for (const hookName of REQUIRED_OBSERVATION_HOOKS) {
    api.on(
      hookName,
      async (payload, context) => client.observeHook(
        hookName,
        normalizeHookPayload(hookName, payload, context, config)
      ),
      hookOptions(hookName)
    );
  }
  api.on(
    OPENCLAW_DELIVERY_HOOK,
    async (event, context) =>
      dispatchOpenClawPushCard(event, context, client, config, {
        commandRunner: options.openclawCommandRunner
      }),
    hookOptions(OPENCLAW_DELIVERY_HOOK)
  );

  for (const toolName of REQUIRED_TOOLS) {
    api.registerTool(createTool(toolName, client));
  }

  if (shouldRegisterNativeMemory(config, options)) {
    registerMemoryCapability(api);
    registerNativeMemoryShim(api, client);
  }
}

function shouldRegisterNativeMemory(config, options) {
  return options.registerNativeMemoryShim === true || config.nativeMemoryTools === true;
}

function registerMemoryCapability(api) {
  if (typeof api.registerMemoryCapability !== "function") {
    return;
  }
  api.registerMemoryCapability({
    promptBuilder(params = {}) {
      const availableTools = params.availableTools instanceof Set ? params.availableTools : new Set();
      const lines = [
        "## MemWing Memory",
        "MemWing is the active long-term collaborative memory system for this agent.",
        "Use MemWing memory for user preferences, durable facts, project context, and cross-session recall.",
        "Do not write user memory to MEMORY.md or memory/*.md unless the user explicitly asks to edit files."
      ];
      if (availableTools.has("memory_search")) {
        lines.push("Use `memory_search` to recall MemWing memories before answering memory-dependent questions.");
      }
      if (availableTools.has("memory_get")) {
        lines.push("Use `memory_get` to inspect a specific MemWing memory item when more evidence is needed.");
      }
      return lines;
    }
  });
}

function registrationClientOptions(api, options) {
  return {
    ...options,
    config: options.config || api.pluginConfig
  };
}

function createContextEngine(api, client, config = {}) {
  return {
    info: CONTEXT_ENGINE_INFO,
    async ingest(params) {
      return client.ingest(normalizeContextEngineEventPayload("ingest", params, config));
    },
    async ingestBatch(params) {
      const events = validateIngestBatchParams(params);
      const results = [];
      for (const event of events) {
        results.push(await client.ingest(normalizeContextEngineEventPayload("ingest", event, config)));
      }
      return {
        accepted: true,
        results,
        traceId: results.find((result) => result && result.traceId)?.traceId || "memwing:ingestBatch"
      };
    },
    async assemble(params) {
      return normalizeAssembleResult(
        await client.assemble(normalizeContextEngineRequestPayload(params, config)),
        params
      );
    },
    async afterTurn(params) {
      return client.afterTurn(normalizeContextEngineEventPayload("afterTurn", params, config));
    },
    async compact(params) {
      const delegation = await delegateCompactionToRuntime(api, params);
      await client.observeHook(
        "after_compaction",
        normalizeHookPayload("after_compaction", { ...params, compactionDelegation: delegation }, {}, config)
      );
      return delegation;
    }
  };
}

function normalizeContextEngineRequestPayload(params, config) {
  const input = isPlainObject(params) ? params : {};
  return withoutUndefined({
    agent_id: resolveAgentId(input),
    workspace_id: resolveWorkspaceId(input, config),
    session_id: resolveSessionId(input),
    prompt: textField(input.prompt),
    messages: Array.isArray(input.messages) ? input.messages : [],
    token_budget: positiveNumberField(input.token_budget) || positiveNumberField(input.tokenBudget),
    available_tools: normalizeAvailableTools(input.available_tools || input.availableTools),
    scope: resolveScope(input, config)
  });
}

function normalizeContextEngineEventPayload(hookName, params, config) {
  const input = isPlainObject(params) ? params : {};
  const messages = Array.isArray(input.messages)
    ? input.messages
    : isPlainObject(input.message)
      ? [input.message]
      : [];
  return withoutUndefined({
    agent_id: resolveAgentId(input),
    workspace_id: resolveWorkspaceId(input, config),
    session_id: resolveSessionId(input),
    run_id: textField(input.run_id) || textField(input.runId),
    message_id:
      textField(input.message_id) ||
      textField(input.messageId) ||
      (isPlainObject(input.message) ? textField(input.message.id) : undefined),
    hook_name: hookName,
    scope: resolveScope(input, config),
    content: textField(input.content) || contextEngineEventContent(hookName, input, messages),
    payload: contextEnginePayload(input, messages),
    event_time: textField(input.event_time) || textField(input.eventTime) || new Date().toISOString()
  });
}

function normalizeAssembleResult(result, params) {
  const inputMessages = Array.isArray(params && params.messages) ? params.messages : [];
  const body = isPlainObject(result) ? result : {};
  const messages = Array.isArray(body.messages) ? body.messages : inputMessages;
  const systemPromptAddition =
    textField(body.systemPromptAddition) ||
    textField(body.system_prompt_addition) ||
    contextBlocksToSystemPromptAddition(body.contextBlocks || body.context_blocks);
  return withoutUndefined({
    messages,
    estimatedTokens: numberField(body.estimatedTokens) || numberField(body.estimated_tokens) || 0,
    systemPromptAddition,
    promptAuthority: promptAuthorityField(body.promptAuthority || body.prompt_authority)
  });
}

function resolveAgentId(input) {
  return (
    textField(input.agent_id) ||
    textField(input.agentId) ||
    agentIdFromSessionKey(textField(input.session_key) || textField(input.sessionKey))
  );
}

function resolveWorkspaceId(input, config) {
  return (
    textField(input.workspace_id) ||
    textField(input.workspaceId) ||
    textField(config && config.workspaceId)
  );
}

function resolveSessionId(input) {
  return (
    textField(input.session_id) ||
    textField(input.sessionId) ||
    textField(input.session_key) ||
    textField(input.sessionKey)
  );
}

function resolveScope(input, config) {
  return isPlainObject(input.scope) ? input.scope : normalizeDefaultScope(config && config.defaultScope);
}

function agentIdFromSessionKey(sessionKey) {
  if (!sessionKey) {
    return undefined;
  }
  const match = /^agent:([^:]+):/.exec(sessionKey);
  return match ? match[1] : undefined;
}

function normalizeAvailableTools(value) {
  if (value instanceof Set) {
    return [...value].filter((item) => typeof item === "string" && item);
  }
  if (Array.isArray(value)) {
    return value.filter((item) => typeof item === "string" && item);
  }
  return undefined;
}

function contextEngineEventContent(hookName, input, messages) {
  const latestMessage = messages.length > 0 ? messages[messages.length - 1] : undefined;
  const messageContent = isPlainObject(latestMessage) ? textContent(latestMessage.content) : undefined;
  if (messageContent) {
    return messageContent;
  }
  if (hookName === "afterTurn") {
    return `OpenClaw context engine afterTurn observed.`;
  }
  return `OpenClaw context engine ${hookName} observed.`;
}

function textContent(value) {
  if (typeof value === "string" && value.trim() !== "") {
    return value;
  }
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (isPlainObject(item)) {
          return textField(item.text) || textField(item.content);
        }
        return undefined;
      })
      .filter(Boolean);
    return parts.length > 0 ? parts.join("\n") : undefined;
  }
  return undefined;
}

function contextEnginePayload(input, messages) {
  const sessionKey = textField(input.sessionKey) || textField(input.session_key);
  return withoutUndefined({
    sessionKey,
    sessionFile: textField(input.sessionFile) || textField(input.session_file),
    platformRef: platformRefFromSessionKey(sessionKey),
    prePromptMessageCount:
      numberField(input.prePromptMessageCount) || numberField(input.pre_prompt_message_count),
    tokenBudget: positiveNumberField(input.tokenBudget) || positiveNumberField(input.token_budget),
    messageCount: messages.length
  });
}

function platformRefFromSessionKey(sessionKey) {
  if (!sessionKey) {
    return undefined;
  }
  const parts = sessionKey.split(":").filter(Boolean);
  if (parts.length < 5 || parts[0] !== "agent") {
    return undefined;
  }
  const channel = parts[2];
  if (channel !== "feishu") {
    return undefined;
  }

  let peerKindIndex = 3;
  if (parts[peerKindIndex + 1] === "direct") {
    peerKindIndex += 1;
  }
  const peerKind = parts[peerKindIndex];
  const peerId = parts[peerKindIndex + 1];
  if (!peerKind || !peerId) {
    return undefined;
  }
  const threadIndex = parts.indexOf("thread", peerKindIndex + 2);
  const threadId = threadIndex >= 0 ? textField(parts[threadIndex + 1]) : undefined;
  if (peerKind === "direct") {
    return withoutUndefined({
      platform: "feishu",
      channel_id: peerId,
      thread_id: threadId,
      receive_id_type: "open_id"
    });
  }
  if (peerKind === "channel" || peerKind === "group") {
    return withoutUndefined({
      platform: "feishu",
      channel_id: peerId,
      thread_id: threadId,
      receive_id_type: "chat_id"
    });
  }
  return undefined;
}

function contextBlocksToSystemPromptAddition(value) {
  if (!Array.isArray(value) || value.length === 0) {
    return undefined;
  }
  const lines = ["MemWing long-term memory context:"];
  for (const item of value) {
    if (!isPlainObject(item)) {
      continue;
    }
    const title = textField(item.title) || textField(item.id) || "Memory";
    const type = textField(item.type);
    const content = textField(item.content);
    const sourceEventIds = Array.isArray(item.source_event_ids)
      ? item.source_event_ids.filter((sourceId) => typeof sourceId === "string" && sourceId)
      : [];
    lines.push(`- ${type ? `${type}: ` : ""}${title}`);
    if (content) {
      lines.push(`  ${content.replace(/\s+/g, " ").trim()}`);
    }
    if (sourceEventIds.length > 0) {
      lines.push(`  Sources: ${sourceEventIds.join(", ")}`);
    }
  }
  return lines.length > 1 ? lines.join("\n") : undefined;
}

function numberField(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
}

function positiveNumberField(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}

function promptAuthorityField(value) {
  if (value === "assembled" || value === "preassembly_may_overflow") {
    return value;
  }
  return undefined;
}

async function delegateCompactionToRuntime(api, params) {
  if (typeof api.delegateCompactionToRuntime === "function") {
    return {
      delegated: true,
      delegate: "openclaw_runtime",
      result: await api.delegateCompactionToRuntime(params)
    };
  }
  return {
    delegated: true,
    delegate: "mock_runtime",
    result: {
      strategy: "runtime_compaction_delegation_mock",
      messageCount: Array.isArray(params && params.messages) ? params.messages.length : 0
    }
  };
}

function createTool(toolName, client) {
  return {
    name: toolName,
    description: `MemWing ${toolName.replaceAll("_", " ")} skeleton tool.`,
    parameters: toolParameters(toolName),
    async execute(...args) {
      const params = toolParams(args);
      if (toolName === "memwing_search_memory") {
        return client.searchMemory(validateSearchParams(params, { modeDefault: "current" }));
      }
      if (toolName === "memwing_get_memory") {
        return client.getMemory(validateMemoryIdParams(params, { includeEvidence: true }));
      }
      if (toolName === "memwing_explain_memory") {
        return client.explainMemory(validateMemoryIdParams(params, { includeEvidence: false }));
      }
      if (toolName === "memwing_search_sources") {
        return client.searchSources(validateSearchParams(params, { modeDefault: "history" }));
      }
      return client.getProjectContext(validateProjectContextParams(params));
    }
  };
}

function registerNativeMemoryShim(api, client) {
  api.registerTool({
    name: "memory_search",
    description: "Compatibility shim for OpenClaw native memory_search.",
    parameters: nativeToolParameters("memory_search"),
    async execute(...args) {
      const params = toolParams(args);
      return client.searchMemory(validateNativeSearchParams(params));
    }
  });
  api.registerTool({
    name: "memory_get",
    description: "Compatibility shim for OpenClaw native memory_get.",
    parameters: nativeToolParameters("memory_get"),
    async execute(...args) {
      const params = toolParams(args);
      return client.getMemory(validateNativeGetParams(params));
    }
  });
  api.registerTool({
    name: "memory_index",
    description: "Compatibility shim for OpenClaw native memory_index.",
    parameters: nativeToolParameters("memory_index"),
    async execute(...args) {
      const params = toolParams(args);
      const indexParams = validateNativeIndexParams(params);
      return client.indexMemory(indexParams);
    }
  });
  api.registerTool({
    name: "memory_status",
    description: "Compatibility shim for OpenClaw native memory_status.",
    parameters: nativeToolParameters("memory_status"),
    async execute(...args) {
      const params = toolParams(args);
      return client.status(validateNativeStatusParams(params));
    }
  });
}

function toolParams(args) {
  if (args.length >= 2 && isPlainObject(args[1])) {
    return args[1];
  }
  return args[0];
}

function validateIngestBatchParams(params) {
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    throw new OpenClawToolSchemaError("params", "params must be an object");
  }
  if (!Array.isArray(params.events)) {
    throw new OpenClawToolSchemaError("events", "events must be an array");
  }
  for (const event of params.events) {
    if (!event || typeof event !== "object" || Array.isArray(event)) {
      throw new OpenClawToolSchemaError("events", "events must contain objects");
    }
  }
  return params.events;
}

function createMockMemWingClient() {
  return {
    async ingest() {
      return {
        accepted: true,
        sourceEventId: "mock-openclaw-source",
        traceId: "memwing:ingest:mock"
      };
    },
    async observeHook(hookName) {
      return {
        accepted: true,
        hookName,
        traceId: `memwing:hook:${hookName}:mock`
      };
    },
    async assemble() {
      return {
        messages: null,
        systemPromptAddition: null,
        contextBlocks: [],
        estimatedTokens: null,
        traceId: "memwing:assemble:mock"
      };
    },
    async afterTurn() {
      return {
        accepted: true,
        traceId: "memwing:afterTurn:mock"
      };
    },
    async searchMemory() {
      return emptySearchEnvelope("memwing:search-memory:mock");
    },
    async getMemory() {
      return {
        item: null,
        evidence: [],
        traceId: "memwing:get-memory:mock"
      };
    },
    async explainMemory(params) {
      return {
        memoryId: params && params.memory_id ? params.memory_id : "unknown",
        sourceEventIds: [],
        rationale: "No memory explanation is available in the MemWing mock client.",
        traceId: "memwing:explain-memory:mock"
      };
    },
    async searchSources() {
      return emptySearchEnvelope("memwing:search-sources:mock");
    },
    async getProjectContext() {
      return {
        messages: null,
        systemPromptAddition: null,
        contextBlocks: [],
        estimatedTokens: null,
        traceId: "memwing:project-context:mock"
      };
    },
    async status() {
      return {
        healthy: true,
        evidenceIndexStatus: "mock_not_connected",
        graphBackendStatus: "mock_not_connected",
        pendingGraphJobs: 0,
        pendingPageJobs: 0,
        capabilities: [
          "context_engine",
          "hook_event_mapping",
          "memwing_tools_empty_envelope",
          "native_memory_shim",
          "runtime_compaction_delegation"
        ],
        traceId: "memwing:status:mock"
      };
    },
    async indexMemory(params) {
      return {
        accepted: true,
        indexed: false,
        force: params && params.force === true,
        traceId: "memwing:native-memory-index:mock"
      };
    },
    async nextOpenClawPushCard() {
      return {
        item: {
          candidate_id: null,
          title: null,
          text: null,
          presentation: null,
          trace_id: "memwing:openclaw-push:mock"
        },
        traceId: "memwing:openclaw-push:mock"
      };
    },
    async ackOpenClawPushCard() {
      return {
        ok: true,
        traceId: "memwing:openclaw-push-ack:mock"
      };
    }
  };
}

function emptySearchEnvelope(traceId) {
  return {
    content: "",
    contexts: [],
    results: [],
    nextCursor: null,
    traceId
  };
}

function normalizeHookPayload(hookName, payload, context, config) {
  const input = isPlainObject(payload) ? payload : {};
  const hookContext = isPlainObject(context) ? context : {};
  const defaultScope = normalizeDefaultScope(config && config.defaultScope);
  return withoutUndefined({
    ...input,
    hook_name: hookName,
    agent_id:
      textField(input.agent_id) ||
      textField(input.agentId) ||
      textField(hookContext.agentId) ||
      agentIdFromSessionKey(
        textField(input.session_key) ||
          textField(input.sessionKey) ||
          textField(hookContext.sessionKey)
      ),
    workspace_id:
      textField(input.workspace_id) ||
      textField(input.workspaceId) ||
      textField(config && config.workspaceId) ||
      textField(hookContext.workspaceDir),
    session_id:
      textField(input.session_id) ||
      textField(input.sessionId) ||
      textField(input.session_key) ||
      textField(input.sessionKey) ||
      textField(hookContext.sessionKey) ||
      textField(hookContext.sessionId),
    run_id: textField(input.run_id) || textField(input.runId) || textField(hookContext.runId),
    scope: isPlainObject(input.scope) ? input.scope : defaultScope,
    content: textField(input.content) || hookContent(hookName, input),
    event_time: textField(input.event_time) || textField(input.eventTime) || new Date().toISOString()
  });
}

async function dispatchOpenClawPushCard(event, context, client, config, options = {}) {
  if (event && (event.sendPolicy === "deny" || event.suppressUserDelivery === true)) {
    return undefined;
  }
  const payload = normalizeReplyDispatchPayload(event, config);
  const target = resolveOpenClawMessageTarget(event, payload);
  if (!target) {
    return undefined;
  }
  let response;
  try {
    response = await client.nextOpenClawPushCard(payload);
  } catch (error) {
    warnOpenClawPush("failed to prepare MemWing push card", error);
    return undefined;
  }
  const item = response && response.item ? response.item : response;
  if (!item || !item.candidate_id || !item.presentation) {
    return undefined;
  }

  const sent = await sendOpenClawMessageCard({
    cli: resolveOpenClawCli(config),
    commandRunner: options.commandRunner,
    target,
    text: textField(item.text) || textField(item.title) || "MemWing memory card",
    presentation: item.presentation
  });
  if (sent && typeof client.ackOpenClawPushCard === "function") {
    try {
      await client.ackOpenClawPushCard(item.candidate_id, {
        ...payload,
        reason: "OpenClaw sent MemWing push card",
        idempotency_key: `${payload.idempotency_key}:ack`
      });
    } catch (error) {
      warnOpenClawPush("failed to ack MemWing push card", error);
    }
  }
  return undefined;
}

function resolveOpenClawCli(config) {
  const explicit = textField(config && config.openclawCli) || textField(process.env.OPENCLAW_CLI);
  if (explicit) {
    return explicit;
  }
  for (const candidate of ["/opt/homebrew/bin/openclaw", "/usr/local/bin/openclaw"]) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return "openclaw";
}

async function sendOpenClawMessageCard({ cli, commandRunner, target, text, presentation }) {
  const args = [
    "message",
    "send",
    "--channel",
    "feishu",
    "--target",
    target,
    "--message",
    text,
    "--presentation",
    JSON.stringify(presentation)
  ];
  try {
    if (typeof commandRunner === "function") {
      await commandRunner({ cli, args });
      return true;
    }
    await runOpenClawCommand(cli, args);
    return true;
  } catch (error) {
    warnOpenClawPush("failed to send MemWing push card through OpenClaw", error);
    return false;
  }
}

function runOpenClawCommand(cli, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cli, args, {
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
        return;
      }
      reject(new Error(stderr.trim() || stdout.trim() || `openclaw exited with code ${code}`));
    });
  });
}

function warnOpenClawPush(message, error) {
  if (typeof console !== "undefined" && typeof console.warn === "function") {
    console.warn(`[memwing] ${message}: ${error && error.message ? error.message : String(error)}`);
  }
}

function normalizeReplyDispatchPayload(event, config) {
  const input = isPlainObject(event) ? event : {};
  const ctx = isPlainObject(input.ctx) ? input.ctx : {};
  const sessionKey = textField(input.sessionKey) || textField(ctx.SessionKey);
  const scope = isPlainObject(input.scope) ? input.scope : normalizeDefaultScope(config && config.defaultScope);
  const runId = textField(input.runId);
  const messageId =
    textField(ctx.MessageSidFull) ||
    textField(ctx.MessageSid) ||
    textField(ctx.MessageSidLast) ||
    textField(ctx.ReplyToIdFull) ||
    textField(ctx.ReplyToId);
  const triggerContent =
    textField(ctx.BodyForCommands) ||
    textField(ctx.CommandBody) ||
    textField(ctx.RawBody) ||
    textField(ctx.Body) ||
    textField(ctx.BodyForAgent);
  const idempotencySeed = runId || messageId || sessionKey || "openclaw-reply-dispatch";
  return withoutUndefined({
    actor_id: "openclaw",
    reason: "OpenClaw reply dispatch requested MemWing push card",
    idempotency_key: `memwing:openclaw-push:${idempotencySeed}`,
    trace_id: `memwing:openclaw-push:${idempotencySeed}`,
    scope,
    trigger_content: triggerContent,
    session_key: sessionKey,
    run_id: runId
  });
}

function resolveOpenClawMessageTarget(event, payload) {
  const input = isPlainObject(event) ? event : {};
  const explicitTarget =
    textField(input.originatingTo) ||
    textField(input.to) ||
    textField(input.target) ||
    textField(input.replyTo);
  if (explicitTarget) {
    return normalizeOpenClawFeishuTarget(explicitTarget);
  }
  const platformRef = platformRefFromSessionKey(textField(payload && payload.session_key));
  if (!platformRef || platformRef.platform !== "feishu") {
    return undefined;
  }
  const channelId = textField(platformRef.channel_id);
  if (!channelId) {
    return undefined;
  }
  if (platformRef.receive_id_type === "open_id") {
    return `user:${channelId}`;
  }
  return `chat:${channelId}`;
}

function normalizeOpenClawFeishuTarget(value) {
  const target = textField(value);
  if (!target) {
    return undefined;
  }
  if (/^(user|dm|open_id|chat|group|channel):/i.test(target)) {
    return target;
  }
  if (target.startsWith("ou_")) {
    return `user:${target}`;
  }
  if (target.startsWith("oc_")) {
    return `chat:${target}`;
  }
  return target;
}

function normalizeDefaultScope(scope) {
  if (!isPlainObject(scope)) {
    return undefined;
  }
  const projectMemorySpaceId = textField(scope.project_memory_space_id);
  if (!projectMemorySpaceId) {
    return undefined;
  }
  return withoutUndefined({
    project_memory_space_id: projectMemorySpaceId,
    group_id: textField(scope.group_id),
    thread_id: textField(scope.thread_id),
    shared_group_id: textField(scope.shared_group_id)
  });
}

function hookContent(hookName, payload) {
  if (hookName === "llm_input") {
    return textField(payload.prompt) || `OpenClaw llm_input hook observed.`;
  }
  if (hookName === "llm_output") {
    const assistantTexts = Array.isArray(payload.assistantTexts)
      ? payload.assistantTexts.filter((item) => typeof item === "string" && item.trim() !== "")
      : [];
    return assistantTexts.join("\n\n") || "OpenClaw llm_output hook observed.";
  }
  if (hookName === "agent_end") {
    return `OpenClaw agent_end hook observed: success=${payload.success === true ? "true" : "false"}.`;
  }
  return `OpenClaw ${hookName} hook observed.`;
}

function textField(value) {
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function withoutUndefined(value) {
  return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined));
}

function hookOptions(hookName) {
  if (hookName === "llm_input" || hookName === "llm_output" || hookName === "agent_end") {
    return {
      allowConversationAccess: true
    };
  }
  return {};
}

function assertOpenClawApi(api) {
  if (!api || typeof api.registerContextEngine !== "function") {
    throw new TypeError("OpenClaw api.registerContextEngine is required");
  }
  if (typeof api.registerTool !== "function") {
    throw new TypeError("OpenClaw api.registerTool is required");
  }
  if (typeof api.on !== "function") {
    throw new TypeError("OpenClaw api.on is required");
  }
}

module.exports = {
  OpenClawToolSchemaError,
  REQUIRED_HOOKS,
  REQUIRED_TOOLS,
  createContextEngine,
  createMemWingHttpClient,
  createMockMemWingClient,
  delegateCompactionToRuntime,
  normalizeHookPayload,
  registrationClientOptions,
  register
};
