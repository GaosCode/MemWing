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
  await registered.tools.get("memory_search").execute({ query: "demo", max_results: 4 });

  assert.deepEqual(searchCalls[0], { query: "demo", limit: 4 });
});

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
