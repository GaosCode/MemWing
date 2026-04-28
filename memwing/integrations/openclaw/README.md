# MemWing OpenClaw Plugin

This package is the v1 local linked OpenClaw plugin skeleton. It registers the MemWing ContextEngine, lifecycle hooks, MemWing knowledge tools, and native memory compatibility shims against a mock MemWing client.

## Configuration

OpenClaw plugin config should enable conversation access because this plugin observes `llm_input`, `llm_output`, and `agent_end`:

```json
{
  "plugins": {
    "entries": {
      "memwing": {
        "enabled": true,
        "hooks": {
          "allowConversationAccess": true
        },
        "config": {
          "memwingBaseUrl": "http://localhost:8000"
        }
      }
    }
  }
}
```

`openclaw.plugin.json` is the manifest source of truth. v1 is distributed as a local linked plugin, not as an npm package or bundled OpenClaw plugin. The skeleton targets OpenClaw `>=2026.4.24 <2027.0.0`; it has mock API smoke coverage and CLI link smoke coverage when the OpenClaw CLI is installed, but it has not been exercised as a real OpenClaw runtime session yet.

## Local Link

```bash
npm run build
openclaw plugin link "$(pwd)"
openclaw plugin unlink memwing
```

## Verification

```bash
npm run typecheck
npm test
npm run smoke
npm run smoke:link
```

`npm run smoke` builds the package, loads `dist/index.js`, registers against a mock OpenClaw API, verifies `registerContextEngine("memwing", ...)`, verifies all required `memwing_*` tools, and checks that `compact()` delegates to the runtime seam instead of returning a no-op.

`npm run smoke:link` builds the package and runs `openclaw plugin link <packageRoot>` with isolated OpenClaw home/config directories. If the OpenClaw CLI is not installed, the Node test reports a skip with the missing CLI reason. If the CLI is present but link fails, the test fails.

Upgrade validation for a new OpenClaw release is: update `openclaw.plugin.json`, run the commands above, run `openclaw plugin link "$(pwd)"` against the target CLI, and run one manual OpenClaw session that exercises ContextEngine `assemble`, `afterTurn`, `compact`, one hook observation, and `memwing_search_memory`.
