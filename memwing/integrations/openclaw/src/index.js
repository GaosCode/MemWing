"use strict";

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

const REQUIRED_HOOKS = [
  "after_tool_call",
  "agent_end",
  "llm_input",
  "llm_output",
  "session_start",
  "session_end",
  "before_compaction",
  "after_compaction"
];

const REQUIRED_TOOLS = [
  "memwing_search_memory",
  "memwing_get_memory",
  "memwing_explain_memory",
  "memwing_search_sources",
  "memwing_get_project_context"
];

function register(api, options = {}) {
  assertOpenClawApi(api);
  const client = options.client || createMemWingHttpClient(registrationClientOptions(api, options));
  api.registerContextEngine("memwing", () => createContextEngine(api, client));

  for (const hookName of REQUIRED_HOOKS) {
    api.on(hookName, async (payload) => client.observeHook(hookName, payload), hookOptions(hookName));
  }

  for (const toolName of REQUIRED_TOOLS) {
    api.registerTool(createTool(toolName, client));
  }

  if (options.registerNativeMemoryShim !== false) {
    registerNativeMemoryShim(api, client);
  }
}

function registrationClientOptions(api, options) {
  return {
    ...options,
    config: options.config || api.pluginConfig
  };
}

function createContextEngine(api, client) {
  return {
    async ingest(params) {
      return client.ingest(params);
    },
    async ingestBatch(params) {
      const events = validateIngestBatchParams(params);
      const results = [];
      for (const event of events) {
        results.push(await client.ingest(event));
      }
      return {
        accepted: true,
        results,
        traceId: results.find((result) => result && result.traceId)?.traceId || "memwing:ingestBatch"
      };
    },
    async assemble(params) {
      return client.assemble(params);
    },
    async afterTurn(params) {
      return client.afterTurn(params);
    },
    async compact(params) {
      const delegation = await delegateCompactionToRuntime(api, params);
      await client.observeHook("after_compaction", {
        ...params,
        compactionDelegation: delegation
      });
      return delegation;
    }
  };
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
    async execute(params) {
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
    async execute(params) {
      return client.searchMemory(validateNativeSearchParams(params));
    }
  });
  api.registerTool({
    name: "memory_get",
    description: "Compatibility shim for OpenClaw native memory_get.",
    parameters: nativeToolParameters("memory_get"),
    async execute(params) {
      return client.getMemory(validateNativeGetParams(params));
    }
  });
  api.registerTool({
    name: "memory_index",
    description: "Compatibility shim for OpenClaw native memory_index.",
    parameters: nativeToolParameters("memory_index"),
    async execute(params) {
      const indexParams = validateNativeIndexParams(params);
      return client.indexMemory(indexParams);
    }
  });
  api.registerTool({
    name: "memory_status",
    description: "Compatibility shim for OpenClaw native memory_status.",
    parameters: nativeToolParameters("memory_status"),
    async execute(params) {
      return client.status(validateNativeStatusParams(params));
    }
  });
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
  registrationClientOptions,
  register
};
