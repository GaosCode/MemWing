"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

test("links the build artifact with the OpenClaw CLI when available", async (t) => {
  const cli = openClawCli();
  const availability = runOpenClaw(cli, ["plugins", "install", "--help"], process.env, null);
  if (availability.error && availability.error.code === "ENOENT") {
    t.skip(`OpenClaw CLI not found: ${cli.label}`);
    return;
  }

  const packageRoot = path.resolve(__dirname, "..");
  const isolatedHome = fs.mkdtempSync(path.join(os.tmpdir(), "memwing-openclaw-link-"));
  const env = isolatedOpenClawEnv(isolatedHome);
  try {
    const linkResult = runOpenClaw(
      cli,
      [
        "plugins",
        "install",
        "--link",
        "--dangerously-force-unsafe-install",
        packageRoot
      ],
      env,
      packageRoot
    );
    assert.equal(
      linkResult.status,
      0,
      commandFailureMessage("openclaw plugins install --link", linkResult)
    );

    const manifest = JSON.parse(
      fs.readFileSync(path.join(packageRoot, "dist", "openclaw.plugin.json"), "utf8")
    );
    const plugin = require(path.join(packageRoot, manifest.entry.replace(/^dist\//, "dist/")));
    const registered = captureRegistrations();

    plugin.register(registered.api);

    assert.equal(manifest.id, "memwing");
    assert.equal(registered.contextEngines[0].id, "memwing");
    for (const toolName of manifest.tools) {
      assert.ok(registered.tools.has(toolName), `${toolName} should register after link`);
    }
  } finally {
    runOpenClaw(cli, ["plugins", "uninstall", "memwing"], env, packageRoot);
    fs.rmSync(isolatedHome, { recursive: true, force: true });
  }
});

function openClawCli() {
  const command = process.env.OPENCLAW_CLI || "openclaw";
  const prefixArgs = splitArgs(process.env.OPENCLAW_CLI_ARGS || "");
  const cwd = process.env.OPENCLAW_CLI_CWD || null;
  return {
    command,
    prefixArgs,
    cwd,
    label: [command, ...prefixArgs].join(" ")
  };
}

function splitArgs(raw) {
  return raw.trim() === "" ? [] : raw.trim().split(/\s+/);
}

function isolatedOpenClawEnv(isolatedHome) {
  return {
    ...process.env,
    HOME: isolatedHome,
    XDG_CONFIG_HOME: path.join(isolatedHome, ".config"),
    XDG_DATA_HOME: path.join(isolatedHome, ".local", "share"),
    OPENCLAW_HOME: path.join(isolatedHome, ".openclaw"),
    OPENCLAW_CONFIG_HOME: path.join(isolatedHome, ".config", "openclaw"),
    OPENCLAW_DATA_HOME: path.join(isolatedHome, ".local", "share", "openclaw")
  };
}

function runOpenClaw(cli, args, env, cwd) {
  return childProcess.spawnSync(cli.command, [...cli.prefixArgs, ...args], {
    cwd: cli.cwd || cwd,
    env,
    encoding: "utf8"
  });
}

function commandFailureMessage(label, result) {
  return [
    `${label} failed with status ${result.status}`,
    result.stdout || "",
    result.stderr || ""
  ].join("\n");
}

function captureRegistrations() {
  const contextEngines = [];
  const tools = new Map();
  return {
    contextEngines,
    tools,
    api: {
      registerContextEngine(id, factory) {
        contextEngines.push({ id, factory });
      },
      on() {},
      registerTool(tool) {
        assert.equal(typeof tool.name, "string");
        tools.set(tool.name, tool);
      },
      async delegateCompactionToRuntime() {
        return {
          strategy: "runtime",
          compacted: true
        };
      }
    }
  };
}
