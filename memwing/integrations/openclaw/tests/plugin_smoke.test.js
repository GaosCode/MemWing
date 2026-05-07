"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const plugin = require("../src/index.js");
const pluginPackage = require("../package.json");

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
    "modelTimeoutSeconds",
    "nativeMemoryTools"
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
  assert.equal(schema.properties.nativeMemoryTools.type, "boolean");
});

test("manifest declares OpenClaw runtime capability and tool contracts", () => {
  const manifestPath = path.resolve(__dirname, "..", "openclaw.plugin.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

  assert.deepEqual(manifest.kind, ["context-engine", "memory"]);
  assert.deepEqual(manifest.contracts.tools, [
    "memwing_search_memory",
    "memwing_get_memory",
    "memwing_explain_memory",
    "memwing_search_sources",
    "memwing_get_project_context",
    "memory_search",
    "memory_get",
    "memory_index",
    "memory_status"
  ]);
});

test("registers MemWing context engine, hooks, and namespaced tools by default", async () => {
  const registered = captureRegistrations();

  plugin.register(registered.api, { client: plugin.createMockMemWingClient() });

  assert.equal(registered.contextEngines[0].id, "memwing");
  assert.deepEqual(registered.hooks.map((hook) => hook.name), plugin.REQUIRED_HOOKS);

  for (const toolName of plugin.REQUIRED_TOOLS) {
    assert.ok(registered.tools.has(toolName), `${toolName} should be registered`);
  }
  for (const shimName of ["memory_search", "memory_get", "memory_index", "memory_status"]) {
    assert.equal(registered.tools.has(shimName), false, `${shimName} should not be registered`);
  }
  assert.equal(registered.memoryCapabilities.length, 0);

  const engine = registered.contextEngines[0].factory();
  assert.deepEqual(engine.info, {
    id: "memwing",
    name: "MemWing",
    version: pluginPackage.version,
    ownsCompaction: false
  });
  const inputMessages = [{ role: "user", content: "hello" }];
  const assembleResult = await engine.assemble({ sessionId: "session_001", messages: inputMessages });
  assert.equal(assembleResult.messages, inputMessages);
  assert.equal(assembleResult.estimatedTokens, 0);
  const compactResult = await engine.compact({ messages: [{ role: "user", content: "hello" }] });

  assert.equal(compactResult.delegated, true);
  assert.equal(registered.delegateCalls.length, 1);
});

test("registers native memory shims only when explicitly requested", () => {
  const registered = captureRegistrations();

  plugin.register(registered.api, {
    client: plugin.createMockMemWingClient(),
    registerNativeMemoryShim: true
  });

  for (const shimName of ["memory_search", "memory_get", "memory_index", "memory_status"]) {
    assert.ok(registered.tools.has(shimName), `${shimName} should be registered`);
  }
  assert.equal(registered.memoryCapabilities.length, 1);
  assert.deepEqual(
    registered.memoryCapabilities[0].promptBuilder({
      availableTools: new Set(["memory_search", "memory_get"])
    }),
    [
      "## MemWing Memory",
      "MemWing is the active long-term collaborative memory system for this agent.",
      "Use MemWing memory for user preferences, durable facts, project context, and cross-session recall.",
      "Do not write user memory to MEMORY.md or memory/*.md unless the user explicitly asks to edit files.",
      "Use `memory_search` to recall MemWing memories before answering memory-dependent questions.",
      "Use `memory_get` to inspect a specific MemWing memory item when more evidence is needed."
    ]
  );
});

test("registers native memory shims from plugin config for memory slot installs", () => {
  const registered = captureRegistrations({
    pluginConfig: {
      nativeMemoryTools: true
    }
  });

  plugin.register(registered.api, { client: plugin.createMockMemWingClient() });

  assert.ok(registered.tools.has("memory_search"));
  assert.equal(registered.memoryCapabilities.length, 1);
});

test("context engine converts MemWing context blocks into OpenClaw assemble output", async () => {
  const registered = captureRegistrations();
  const assembleCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async assemble(params) {
      assembleCalls.push(params);
      return {
        messages: null,
        system_prompt_addition: null,
        context_blocks: [
          {
            type: "current_truth",
            id: "memory_001",
            title: "Launch plan",
            content: "Alice owns the launch checklist.",
            source_event_ids: ["source_001"]
          }
        ],
        estimated_tokens: null,
        trace_id: "trace_context"
      };
    }
  };

  plugin.register(registered.api, { client });

  const engine = registered.contextEngines[0].factory();
  const inputMessages = [{ role: "user", content: "Who owns launch?" }];
  const result = await engine.assemble({
    sessionId: "session_001",
    sessionKey: "agent:main:explicit:session_001",
    messages: inputMessages,
    tokenBudget: 4096,
    availableTools: new Set(["memwing_search_memory"]),
    prompt: "Who owns launch?"
  });

  assert.equal(assembleCalls[0].agent_id, "main");
  assert.equal(assembleCalls[0].session_id, "session_001");
  assert.deepEqual(assembleCalls[0].messages, inputMessages);
  assert.equal(assembleCalls[0].token_budget, 4096);
  assert.deepEqual(assembleCalls[0].available_tools, ["memwing_search_memory"]);
  assert.equal(result.messages, inputMessages);
  assert.equal(result.estimatedTokens, 0);
  assert.match(result.systemPromptAddition, /MemWing long-term memory context/);
  assert.match(result.systemPromptAddition, /Alice owns the launch checklist/);
  assert.match(result.systemPromptAddition, /source_001/);
});

test("context engine maps OpenClaw lifecycle params before posting to MemWing", async () => {
  const registered = captureRegistrations({
    pluginConfig: {
      memwingBaseUrl: "http://localhost:8000",
      workspaceId: "workspace_001",
      defaultScope: {
        project_memory_space_id: "project_001"
      }
    }
  });
  const afterTurnCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async afterTurn(params) {
      afterTurnCalls.push(params);
      return {
        accepted: true,
        traceId: "trace_after_turn"
      };
    }
  };

  plugin.register(registered.api, { client, config: registered.api.pluginConfig });

  const engine = registered.contextEngines[0].factory();
  await engine.afterTurn({
    sessionId: "session_001",
    sessionKey: "agent:main:explicit:session_001",
    sessionFile: "/tmp/session.jsonl",
    messages: [
      { role: "user", content: "Who owns launch?" },
      { role: "assistant", content: "Alice owns launch." }
    ],
    prePromptMessageCount: 1,
    tokenBudget: 4096
  });

  assert.equal(afterTurnCalls[0].agent_id, "main");
  assert.equal(afterTurnCalls[0].workspace_id, "workspace_001");
  assert.equal(afterTurnCalls[0].session_id, "session_001");
  assert.equal(afterTurnCalls[0].hook_name, "afterTurn");
  assert.deepEqual(afterTurnCalls[0].scope, { project_memory_space_id: "project_001" });
  assert.equal(afterTurnCalls[0].content, "Alice owns launch.");
  assert.match(afterTurnCalls[0].event_time, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(afterTurnCalls[0].payload.sessionKey, "agent:main:explicit:session_001");
  assert.equal(afterTurnCalls[0].payload.messageCount, 2);
});

test("context engine events include Feishu platform ref from session key", async () => {
  const registered = captureRegistrations({
    config: {
      workspaceId: "workspace_001",
      defaultScope: {
        project_memory_space_id: "project_001"
      }
    }
  });
  const afterTurnCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async afterTurn(params) {
      afterTurnCalls.push(params);
      return {
        accepted: true,
        traceId: "trace_after_turn"
      };
    }
  };

  plugin.register(registered.api, { client, config: registered.api.pluginConfig });

  const engine = registered.contextEngines[0].factory();
  await engine.afterTurn({
    sessionId: "session_001",
    sessionKey: "agent:main:feishu:channel:oc_demo_chat",
    messages: [{ role: "assistant", content: "Decision recorded." }]
  });

  assert.deepEqual(afterTurnCalls[0].payload.platformRef, {
    platform: "feishu",
    channel_id: "oc_demo_chat",
    receive_id_type: "chat_id"
  });
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

test("reply dispatch sends MemWing push cards through OpenClaw message action", async () => {
  const registered = captureRegistrations({
    pluginConfig: {
      memwingBaseUrl: "http://localhost:8000",
      workspaceId: "workspace_001",
      defaultScope: {
        project_memory_space_id: "project_001"
      }
    }
  });
  const nextCalls = [];
  const ackCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async nextOpenClawPushCard(params) {
      nextCalls.push(params);
      return {
        item: {
          candidate_id: "push_001",
          title: "Demo 项目负责人",
          text: "Demo 负责人：gao",
          presentation: {
            title: "Demo 项目负责人",
            tone: "info",
            blocks: [{ type: "text", text: "Demo 负责人：gao" }]
          }
        }
      };
    },
    async ackOpenClawPushCard(candidateId, params) {
      ackCalls.push({ candidateId, params });
      return { ok: true };
    }
  };
  const commands = [];
  const dispatcher = {
    sendBlockReply(payload) {
      throw new Error(`expected MemWing cards to use OpenClaw message action, got ${JSON.stringify(payload)}`);
    },
    sendFinalReply(payload) {
      throw new Error(`expected MemWing cards to use OpenClaw message action, got ${JSON.stringify(payload)}`);
    }
  };
  const commandRunner = async (command) => {
    commands.push(command);
  };

  plugin.register(registered.api, {
    client,
    config: {
      ...registered.api.pluginConfig,
      openclawCli: "openclaw-bin"
    },
    openclawCommandRunner: commandRunner
  });
  const replyDispatchHook = registered.hooks.find((hook) => hook.name === "reply_dispatch");
  const result = await replyDispatchHook.handler(
    {
      runId: "run_001",
      sessionKey: "agent:main:feishu:direct:ou_user",
      sendPolicy: "allow",
      ctx: {
        SessionKey: "agent:main:feishu:direct:ou_user",
        BodyForCommands: "提醒一下 demo 项目记忆，有什么负责人信息？",
        MessageSid: "om_001"
      }
    },
    { dispatcher }
  );

  assert.equal(result, undefined);
  assert.equal(nextCalls.length, 1);
  assert.deepEqual(nextCalls[0].scope, { project_memory_space_id: "project_001" });
  assert.equal(nextCalls[0].trigger_content, "提醒一下 demo 项目记忆，有什么负责人信息？");
  assert.equal(commands.length, 1);
  assert.deepEqual(commands[0], {
    cli: "openclaw-bin",
    args: [
      "message",
      "send",
      "--channel",
      "feishu",
      "--target",
      "user:ou_user",
      "--message",
      "Demo 负责人：gao",
      "--presentation",
      JSON.stringify({
        title: "Demo 项目负责人",
        tone: "info",
        blocks: [{ type: "text", text: "Demo 负责人：gao" }]
      })
    ]
  });
  assert.deepEqual(ackCalls, [
    {
      candidateId: "push_001",
      params: {
        ...nextCalls[0],
        reason: "OpenClaw sent MemWing push card",
        idempotency_key: "memwing:openclaw-push:run_001:ack"
      }
    }
  ]);
});

test("reply dispatch leaves candidates unacked when OpenClaw message send fails", async () => {
  const registered = captureRegistrations({
    pluginConfig: {
      memwingBaseUrl: "http://localhost:8000",
      workspaceId: "workspace_001",
      defaultScope: {
        project_memory_space_id: "project_001"
      }
    }
  });
  const ackCalls = [];
  const client = {
    ...plugin.createMockMemWingClient(),
    async nextOpenClawPushCard() {
      return {
        item: {
          candidate_id: "push_001",
          title: "Demo 项目负责人",
          text: "Demo 负责人：gao",
          presentation: {
            title: "Demo 项目负责人",
            tone: "info",
            blocks: [{ type: "text", text: "Demo 负责人：gao" }]
          }
        }
      };
    },
    async ackOpenClawPushCard(candidateId, params) {
      ackCalls.push({ candidateId, params });
      return true;
    }
  };

  plugin.register(registered.api, {
    client,
    config: registered.api.pluginConfig,
    openclawCommandRunner: async () => {
      throw new Error("send failed");
    }
  });
  const replyDispatchHook = registered.hooks.find((hook) => hook.name === "reply_dispatch");
  const result = await replyDispatchHook.handler(
    {
      runId: "run_001",
      sessionKey: "agent:main:feishu:direct:ou_user",
      sendPolicy: "allow",
      ctx: {
        SessionKey: "agent:main:feishu:direct:ou_user",
        BodyForCommands: "提醒一下 demo 项目记忆，有什么负责人信息？",
        MessageSid: "om_001"
      }
    },
    {
      dispatcher: {
        sendBlockReply() {
          throw new Error("not expected");
        },
        sendFinalReply() {
          throw new Error("not expected");
        }
      }
    }
  );

  assert.equal(result, undefined);
  assert.deepEqual(ackCalls, []);
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

  plugin.register(registered.api, { client, registerNativeMemoryShim: true });
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

test("tools accept OpenClaw runtime execute signature", async () => {
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

  plugin.register(registered.api, {
    client,
    registerNativeMemoryShim: true
  });

  await registered.tools.get("memwing_search_memory").execute("tool-call-001", {
    agent_id: "main",
    query: "demo",
    scope: scope()
  });
  await registered.tools.get("memory_search").execute("tool-call-002", {
    agent_id: "main",
    query: "demo",
    scope: scope()
  });

  assert.deepEqual(searchCalls[0], {
    agent_id: "main",
    query: "demo",
    scope: scope(),
    mode: "current",
    limit: 20,
    sort: "relevance",
    min_score: 0
  });
  assert.deepEqual(searchCalls[1], {
    agent_id: "main",
    query: "demo",
    scope: scope(),
    mode: "current",
    limit: 20,
    sort: "relevance",
    min_score: 0
  });
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

  plugin.register(registered.api, { client, registerNativeMemoryShim: true });

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
  const memoryCapabilities = [];
  const delegateCalls = [];
  return {
    contextEngines,
    hooks,
    tools,
    memoryCapabilities,
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
      registerMemoryCapability(capability) {
        memoryCapabilities.push(capability);
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
