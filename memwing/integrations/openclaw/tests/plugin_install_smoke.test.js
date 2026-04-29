"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("loads from build artifact and follows manifest entry without CLI link", async () => {
  const packageRoot = path.resolve(__dirname, "..");
  const manifestPath = path.join(packageRoot, "dist", "openclaw.plugin.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const plugin = require(path.join(packageRoot, manifest.entry.replace(/^dist\//, "dist/")));
  const registered = captureRegistrations();

  plugin.register(registered.api, { client: plugin.createMockMemWingClient() });

  assert.equal(manifest.id, "memwing");
  assert.equal(registered.contextEngines[0].id, "memwing");
  for (const toolName of manifest.tools) {
    assert.ok(registered.tools.has(toolName), `${toolName} should be registered from dist`);
  }

  const engine = registered.contextEngines[0].factory();
  const compactResult = await engine.compact({ messages: [] });

  assert.equal(compactResult.delegated, true);
  assert.equal(registered.delegateCalls.length, 1);
});

function captureRegistrations() {
  const contextEngines = [];
  const tools = new Map();
  const delegateCalls = [];
  return {
    contextEngines,
    tools,
    delegateCalls,
    api: {
      registerContextEngine(id, factory) {
        contextEngines.push({ id, factory });
      },
      on() {},
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
