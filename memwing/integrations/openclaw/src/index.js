"use strict";

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
  const client = options.client || createMockMemWingClient(options);
  api.registerContextEngine("memwing", () => createContextEngine(api, client));

  for (const hookName of REQUIRED_HOOKS) {
    api.on(hookName, async (payload) => client.observeHook(hookName, payload), hookOptions(hookName));
  }

  for (const toolName of REQUIRED_TOOLS) {
    api.registerTool(toolName, createTool(toolName, client));
  }

  if (options.registerNativeMemoryShim !== false) {
    registerNativeMemoryShim(api, client);
  }
}

function createContextEngine(api, client) {
  return {
    async ingest(params) {
      return client.ingest(params);
    },
    async ingestBatch(params) {
      const events = Array.isArray(params && params.events) ? params.events : [];
      const results = [];
      for (const event of events) {
        results.push(await client.ingest(event));
      }
      return {
        accepted: true,
        results,
        traceId: "memwing:ingestBatch:mock"
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
    parameters: {
      type: "object"
    },
    async execute(params) {
      if (toolName === "memwing_search_memory") {
        return client.searchMemory(params);
      }
      if (toolName === "memwing_get_memory") {
        return client.getMemory(params);
      }
      if (toolName === "memwing_explain_memory") {
        return client.explainMemory(params);
      }
      if (toolName === "memwing_search_sources") {
        return client.searchSources(params);
      }
      return client.getProjectContext(params);
    }
  };
}

function registerNativeMemoryShim(api, client) {
  api.registerTool("memory_search", {
    name: "memory_search",
    description: "Compatibility shim for OpenClaw native memory_search.",
    parameters: {
      type: "object"
    },
    async execute(params) {
      const limit = Number.isInteger(params && params.max_results) ? params.max_results : 20;
      const canonicalParams = { ...(params || {}) };
      delete canonicalParams.max_results;
      return client.searchMemory({
        ...canonicalParams,
        limit
      });
    }
  });
  api.registerTool("memory_get", {
    name: "memory_get",
    description: "Compatibility shim for OpenClaw native memory_get.",
    parameters: {
      type: "object"
    },
    async execute(params) {
      return client.getMemory(params);
    }
  });
  api.registerTool("memory_index", {
    name: "memory_index",
    description: "Compatibility shim for OpenClaw native memory_index.",
    parameters: {
      type: "object"
    },
    async execute(params) {
      return {
        accepted: true,
        indexed: false,
        force: Boolean(params && params.force),
        traceId: "memwing:native-memory-index:mock"
      };
    }
  });
  api.registerTool("memory_status", {
    name: "memory_status",
    description: "Compatibility shim for OpenClaw native memory_status.",
    parameters: {
      type: "object"
    },
    async execute(params) {
      return client.status(params);
    }
  });
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
  REQUIRED_HOOKS,
  REQUIRED_TOOLS,
  createContextEngine,
  createMockMemWingClient,
  delegateCompactionToRuntime,
  register
};
