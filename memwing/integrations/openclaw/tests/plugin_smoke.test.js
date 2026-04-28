"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const plugin = require("../src/index.js");

test("registers MemWing context engine, hooks, tools, and native shims", async () => {
  const registered = captureRegistrations();

  plugin.register(registered.api);

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

test("all memwing tools reject missing required fields before calling the client", async () => {
  const registered = captureRegistrations();

  plugin.register(registered.api);

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
    max_results: 4,
    scope: scope()
  });

  assert.deepEqual(searchCalls[0], {
    agent_id: "main",
    query: "demo",
    scope: scope(),
    mode: "current",
    limit: 4,
    sort: "relevance",
    min_score: 0
  });
  assert.equal(Object.hasOwn(searchCalls[0], "max_results"), false);
});

function scope() {
  return {
    project_memory_space_id: "project_001"
  };
}

function captureRegistrations() {
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
      registerContextEngine(id, factory) {
        contextEngines.push({ id, factory });
      },
      on(name, handler, options) {
        hooks.push({ name, handler, options });
      },
      registerTool(name, tool) {
        tools.set(name, tool);
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
