"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const plugin = require("../src/index.js");

test("manifest config schema accepts documented MemWing base URL", () => {
  const manifestPath = path.resolve(__dirname, "..", "openclaw.plugin.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const schema = manifest.configSchema;

  assert.equal(schema.type, "object");
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(Object.keys(schema.properties), [
    "memwingBaseUrl",
    "workspaceId",
    "defaultScope",
    "modelRuntime",
    "models",
    "modelTimeoutSeconds"
  ]);
  assert.equal(schema.properties.memwingBaseUrl.type, "string");
  assert.equal(schema.properties.memwingBaseUrl.minLength, 1);
  assert.deepEqual(schema.properties.workspaceId.type, ["string", "null"]);
  assert.deepEqual(schema.properties.defaultScope.required, ["project_memory_space_id"]);
  assert.deepEqual(schema.properties.modelRuntime.enum, ["openclaw"]);
  assert.deepEqual(Object.keys(schema.properties.models.properties), [
    "pageMemory",
    "longTermFilter",
    "graphitiExtraction",
    "graphitiEmbedding",
    "graphitiRerank",
    "evidenceEmbedding"
  ]);
});

test("registers MemWing context engine, hooks, tools, and native shims", async () => {
  const registered = captureRegistrations();

  plugin.register(registered.api, { client: plugin.createMockMemWingClient() });

  assert.equal(registered.contextEngines[0].id, "memwing");
  assert.deepEqual(registered.hooks.map((hook) => hook.name), plugin.REQUIRED_HOOKS);

  for (const toolName of plugin.REQUIRED_TOOLS) {
    assert.ok(registered.tools.has(toolName), `${toolName} should be registered`);
  }
  for (const shimName of ["memory_search", "memory_get", "memory_index", "memory_status"]) {
    assert.ok(registered.tools.has(shimName), `${shimName} should be registered`);
  }

  const engine = registered.contextEngines[0].factory();
  const compactResult = await engine.compact({ messages: [{ role: "user", content: "hello" }] });

  assert.equal(compactResult.delegated, true);
  assert.equal(registered.delegateCalls.length, 1);
});

test("ingestBatch rejects malformed batch shapes", async () => {
  const registered = captureRegistrations();

  plugin.register(registered.api, { client: plugin.createMockMemWingClient() });

  const engine = registered.contextEngines[0].factory();
  await assert.rejects(() => engine.ingestBatch(), { name: "OpenClawToolSchemaError" });
  await assert.rejects(
    () => engine.ingestBatch({ events: "not-array" }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "events");
      return true;
    }
  );
  await assert.rejects(
    () => engine.ingestBatch({ events: ["bad-event"] }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "events");
      return true;
    }
  );
});

test("memwing_search_memory rejects invalid input and returns explicit empty envelope for valid input", async () => {
  const registered = captureRegistrations();
  const searchCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async searchMemory(params) {
      searchCalls.push(params);
      return {
        content: "",
        contexts: [],
        results: [],
        nextCursor: null,
        traceId: "memwing:search-memory:mock"
      };
    }
  };

  plugin.register(registered.api, { client });

  const tool = registered.tools.get("memwing_search_memory");
  assert.deepEqual(tool.parameters.required, ["agent_id", "query", "scope"]);
  assert.equal(tool.parameters.additionalProperties, false);
  assert.equal(tool.parameters.properties.scope.additionalProperties, false);
  await assert.rejects(
    () => tool.execute({ agent_id: "main" }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.code, "schema_validation_failed");
      assert.equal(error.field, "scope");
      return true;
    }
  );
  await assert.rejects(
    () => tool.execute({ agent_id: "main", scope: scope() }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.code, "schema_validation_failed");
      assert.equal(error.field, "query");
      return true;
    }
  );
  await assert.rejects(
    () => tool.execute({ agent_id: "main", query: "demo scope", max_results: 9, scope: scope() }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.code, "schema_validation_failed");
      assert.equal(error.field, "max_results");
      return true;
    }
  );
  await assert.rejects(
    () => tool.execute({
      agent_id: "main",
      query: "demo scope",
      scope: {
        project_memory_space_id: "project_001",
        unexpected: "accepted"
      }
    }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.code, "schema_validation_failed");
      assert.equal(error.field, "unexpected");
      return true;
    }
  );

  const result = await tool.execute({
    agent_id: "main",
    query: "demo scope",
    limit: 3,
    cursor: "cursor_001",
    sort: "event_time",
    min_score: 0.25,
    scope: {
      project_memory_space_id: "project_001",
      group_id: "group_001"
    }
  });

  assert.deepEqual(result, {
    content: "",
    contexts: [],
    results: [],
    nextCursor: null,
    traceId: "memwing:search-memory:mock"
  });
  assert.deepEqual(searchCalls[0], {
    agent_id: "main",
    query: "demo scope",
    scope: {
      project_memory_space_id: "project_001",
      group_id: "group_001"
    },
    mode: "current",
    limit: 3,
    cursor: "cursor_001",
    sort: "event_time",
    min_score: 0.25
  });
  assert.equal(Object.hasOwn(searchCalls[0], "max_results"), false);
});

test("conversation hooks enrich OpenClaw context before posting to MemWing", async () => {
  const registered = captureRegistrations({
    pluginConfig: {
      memwingBaseUrl: "http://localhost:8000",
      workspaceId: "workspace_001",
      defaultScope: {
        project_memory_space_id: "project_001",
        group_id: "group_001"
      }
    }
  });
  const hookCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async observeHook(hookName, params) {
      hookCalls.push({ hookName, params });
      return {
        accepted: true,
        sourceEventId: "source_001",
        traceId: "trace_hook"
      };
    }
  };

  plugin.register(registered.api, { client, config: registered.api.pluginConfig });
  const llmInputHook = registered.hooks.find((hook) => hook.name === "llm_input");
  await llmInputHook.handler(
    {
      runId: "run_001",
      sessionId: "session_001",
      prompt: "Remember the MemWing session smoke result."
    },
    {
      agentId: "main",
      sessionKey: "agent:main:explicit:session_001",
      workspaceDir: "/tmp/openclaw-workspace"
    }
  );

  assert.equal(hookCalls.length, 1);
  assert.equal(hookCalls[0].hookName, "llm_input");
  assert.equal(hookCalls[0].params.agent_id, "main");
  assert.equal(hookCalls[0].params.workspace_id, "workspace_001");
  assert.equal(hookCalls[0].params.session_id, "session_001");
  assert.equal(hookCalls[0].params.run_id, "run_001");
  assert.equal(hookCalls[0].params.hook_name, "llm_input");
  assert.deepEqual(hookCalls[0].params.scope, {
    project_memory_space_id: "project_001",
    group_id: "group_001"
  });
  assert.equal(hookCalls[0].params.content, "Remember the MemWing session smoke result.");
  assert.match(hookCalls[0].params.event_time, /^\d{4}-\d{2}-\d{2}T/);
});

test("all memwing tools reject missing required fields before calling the client", async () => {
  const registered = captureRegistrations();

  plugin.register(registered.api, { client: plugin.createMockMemWingClient() });

  const invalidCalls = [
    ["memwing_get_memory", { agent_id: "main", scope: scope() }, "memory_id"],
    ["memwing_explain_memory", { agent_id: "main", scope: scope() }, "memory_id"],
    ["memwing_search_sources", { agent_id: "main", scope: scope() }, "query"],
    ["memwing_get_project_context", { agent_id: "main" }, "scope"]
  ];

  for (const [toolName, payload, field] of invalidCalls) {
    await assert.rejects(
      () => registered.tools.get(toolName).execute(payload),
      (error) => {
        assert.equal(error.name, "OpenClawToolSchemaError");
        assert.equal(error.field, field);
        return true;
      }
    );
  }
});

test("register requires backend config unless a test client is explicit", () => {
  assert.throws(
    () => plugin.register(captureRegistrations().api),
    /memwingBaseUrl is required/
  );

  const registered = captureRegistrations();
  plugin.register(registered.api, { memwingBaseUrl: "http://localhost:8000" });

  assert.equal(registered.contextEngines[0].id, "memwing");
});

test("register reads backend config from OpenClaw plugin config", () => {
  const registered = captureRegistrations({
    pluginConfig: {
      memwingBaseUrl: "http://localhost:8000"
    }
  });

  plugin.register(registered.api);

  assert.equal(registered.contextEngines[0].id, "memwing");
  assert.ok(registered.tools.has("memwing_search_memory"));
});

test("native memory_search converts max_results before calling MemWing client", async () => {
  const registered = captureRegistrations();
  const searchCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async searchMemory(params) {
      searchCalls.push(params);
      return {
        contexts: [],
        results: [],
        nextCursor: null,
        traceId: "trace"
      };
    }
  };

  plugin.register(registered.api, { client });
  await registered.tools.get("memory_search").execute({
    agent_id: "main",
    query: "demo",
    mode: "history",
    max_results: 4,
    min_score: 0.25,
    scope: scope()
  });

  assert.deepEqual(searchCalls[0], {
    agent_id: "main",
    query: "demo",
    scope: scope(),
    mode: "history",
    limit: 4,
    sort: "relevance",
    min_score: 0.25
  });
  assert.equal(Object.hasOwn(searchCalls[0], "max_results"), false);
});

test("native memory shims reject bad input before returning mock success", async () => {
  const registered = captureRegistrations();
  const getCalls = [];
  const statusCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async getMemory(params) {
      getCalls.push(params);
      return {
        item: null,
        evidence: [],
        traceId: "trace"
      };
    },
    async status(params) {
      statusCalls.push(params);
      return {
        healthy: true,
        traceId: "trace"
      };
    }
  };

  plugin.register(registered.api, { client });

  await assert.rejects(
    () => registered.tools.get("memory_search").execute({
      agent_id: "main",
      query: "demo",
      max_results: 4,
      unexpected: "accepted",
      scope: scope()
    }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "unexpected");
      return true;
    }
  );
  await assert.rejects(
    () => registered.tools.get("memory_search").execute({
      agent_id: "main",
      query: "demo",
      mode: "unknown",
      max_results: 4,
      scope: scope()
    }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "mode");
      return true;
    }
  );
  await assert.rejects(
    () => registered.tools.get("memory_search").execute({
      agent_id: "main",
      query: "demo",
      max_results: 4,
      min_score: "0.25",
      scope: scope()
    }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "min_score");
      return true;
    }
  );
  await assert.rejects(
    () => registered.tools.get("memory_get").execute({
      agent_id: "main",
      memory_id: "memory_001",
      unexpected: "accepted",
      scope: scope()
    }),
    { name: "OpenClawToolSchemaError" }
  );
  await assert.rejects(
    () => registered.tools.get("memory_index").execute({ force: "yes" }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "force");
      return true;
    }
  );
  await assert.rejects(
    () => registered.tools.get("memory_index").execute({
      force: "yes",
      unexpected: "accepted"
    }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "unexpected");
      return true;
    }
  );
  await assert.rejects(
    () => registered.tools.get("memory_index").execute({ force: true, unexpected: "accepted" }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "unexpected");
      return true;
    }
  );
  await assert.rejects(
    () => registered.tools.get("memory_status").execute({ agent_id: "main", deep: "yes" }),
    (error) => {
      assert.equal(error.name, "OpenClawToolSchemaError");
      assert.equal(error.field, "deep");
      return true;
    }
  );

  const indexResult = await registered.tools.get("memory_index").execute({ force: true });
  const getResult = await registered.tools.get("memory_get").execute({
    agent_id: "main",
    memory_id: "memory_001",
    include_evidence: true,
    scope: scope()
  });
  const statusResult = await registered.tools.get("memory_status").execute({
    agent_id: "main",
    project_memory_space_id: "project_001",
    deep: true
  });

  assert.equal(indexResult.accepted, true);
  assert.equal(indexResult.force, true);
  assert.equal(getResult.traceId, "trace");
  assert.deepEqual(getCalls[0], {
    agent_id: "main",
    memory_id: "memory_001",
    include_evidence: true,
    scope: scope()
  });
  assert.equal(statusResult.traceId, "trace");
  assert.deepEqual(statusCalls[0], {
    agent_id: "main",
    project_memory_space_id: "project_001",
    deep: true
  });
});

function scope() {
  return {
    project_memory_space_id: "project_001"
  };
}

function captureRegistrations(params = {}) {
  const contextEngines = [];
  const hooks = [];
  const tools = new Map();
  const delegateCalls = [];
  return {
    contextEngines,
    hooks,
    tools,
    delegateCalls,
    api: {
      pluginConfig: params.pluginConfig,
      registerContextEngine(id, factory) {
        contextEngines.push({ id, factory });
      },
      on(name, handler, options) {
        hooks.push({ name, handler, options });
      },
      registerTool(tool) {
        assert.equal(typeof tool.name, "string");
        tools.set(tool.name, tool);
      },
      async delegateCompactionToRuntime(params) {
        delegateCalls.push(params);
        return {
          strategy: "runtime",
          compacted: true
        };
      }
    }
  };
}
