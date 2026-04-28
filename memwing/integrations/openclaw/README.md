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

`openclaw.plugin.json` is the manifest source of truth. v1 is distributed as a local linked plugin, not as an npm package or bundled OpenClaw plugin.

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
```

The smoke test loads `dist/index.js`, registers against a mock OpenClaw API, verifies `registerContextEngine("memwing", ...)`, verifies all required `memwing_*` tools, and checks that `compact()` delegates to the runtime seam instead of returning a no-op.
