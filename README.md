<p align="center">
  <img src="frontend/src/shared/assets/memwing-mark.svg" alt="MemWing mark" width="96">
</p>

<h1 align="center">MemWing</h1>

<p align="center">
  <strong>Long-term collaborative memory for workplace agents.</strong>
</p>

<p align="center">
  MemWing gives workplace agents a governable memory layer: capture Source Events,
  build Current Truth, surface project context, manage memory lifecycle, and push
  timely reminders back into collaboration flows.
</p>

<p align="center">
  <a href="https://github.com/GaosCode/MemWing"><img src="https://img.shields.io/badge/GitHub-GaosCode%2FMemWing-181717?style=for-the-badge&logo=github" alt="GitHub repository"></a>
  <img src="https://img.shields.io/badge/Python-3.13%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.13+">
  <img src="https://img.shields.io/badge/OpenClaw-Agent_Runtime-111827?style=for-the-badge" alt="OpenClaw runtime">
  <img src="https://img.shields.io/badge/Lark-Collaboration-00D6B9?style=for-the-badge" alt="Lark collaboration">
  <img src="https://img.shields.io/badge/FastAPI-API-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <a href="#license"><img src="https://img.shields.io/badge/License-Apache_2.0-blue?style=for-the-badge" alt="Apache 2.0 license"></a>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> |
  <a href="#control-plane">Control Plane</a> |
  <a href="#runtime-profiles">Runtime Profiles</a> |
  <a href="#architecture">Architecture</a> |
  <a href="#cli">CLI</a> |
  <a href="#license">License</a> |
  <a href="readme/README.zh-CN.md">中文</a>
</p>

---

## Why MemWing

Most workplace agents are clever but forgetful. They can answer the current
prompt, but lose the thread across project decisions, Lark discussions, tool
runs, shifting deadlines, and "we already decided this last week" moments.

MemWing is a long-term collaborative memory system for those agents. It stores
authoritative Source Events, derives recallable memory layers, tracks what is
current versus historical, and gives humans a Control Plane for review,
redaction, lifecycle changes, and proactive push.

It is built for teams that need memory to be useful, explainable, and governable.

## Quickstart

The happy path is designed to feel like installing a normal local tool.

```bash
brew install memwing
memwing quickstart
```

Prefer an install script?

```bash
curl -fsSL https://raw.githubusercontent.com/GaosCode/MemWing/main/packaging/install.sh | sh
memwing quickstart
```

`memwing quickstart` uses the Lite profile by default. It creates local state,
links the OpenClaw plugin, configures the context engine, and starts the MemWing
runtime.

```bash
memwing status
memwing doctor
```

## Control Plane

MemWing is not only a memory API. It includes a Control Plane for humans to
inspect and govern what agents remember.

```bash
memwing control-plane
```

Use the Control Plane to:

- review Memory Items before they become trusted long-term context
- inspect Source Events behind an answer or push candidate
- approve, archive, redact, or purge memory with a reason
- monitor Page Memory, pipeline readiness, and maintenance queues
- send proactive memory cards back into workplace collaboration flows

## Runtime Profiles

| Profile | Best For | Storage | Derived Backends | Setup |
| --- | --- | --- | --- | --- |
| **Lite** | personal trials, demos, OpenClaw users who do not want databases | SQLite | graph and evidence disabled | `memwing quickstart` |
| **Full Local** | local evaluation with full retrieval stack | Postgres | Qdrant + Neo4j / Graphiti | `memwing quickstart --profile full-local` |
| **Production** | managed infrastructure for teams | Postgres | managed Qdrant + Neo4j / Graphiti | `memwing setup --profile production` |

Lite is intentionally close to consumer software: no Docker, no Postgres, no
Qdrant, no Neo4j, and no separate model credentials. By default, model calls go
through the agent runtime.

## OpenClaw And Lark

MemWing is platform-neutral, but today it has a first-class OpenClaw path and
workplace collaboration flows designed around Lark.

With OpenClaw, MemWing provides:

- a ContextEngine for context assembly, after-turn capture, and compaction
- conversation hooks for Source Event capture
- tools for memory search, source lookup, project context, and explanation
- native-memory compatibility shims for agent workflows

With Lark-style workplace flows, MemWing is designed to remember:

- project decisions and their reasons
- changing preferences and deadlines
- recurring team workflows
- information that should be resurfaced before it is forgotten


Core vocabulary:

- **Source Event**: the authoritative raw collaboration event.
- **Current Truth**: the effective fact set preferred at recall time.
- **Page Memory**: editable mid-term project or thread summary.
- **Memory Item**: governable long-term memory with lifecycle state.
- **Evidence Index**: derived retrieval layer over Source Events.
- **Graph Backend**: entity and relationship layer for validity and history.
- **Control Plane**: human governance surface for memory review and operations.

## CLI

```bash
# One-command local setup
memwing quickstart

# Start runtime from existing config
memwing start

# Inspect local configuration and health
memwing status
memwing doctor

# Open the memory governance UI
memwing control-plane

# Install or inspect the OpenClaw plugin
memwing openclaw install
memwing openclaw status

# Production config skeleton
memwing setup --profile production
```

Automation and scripts can also call the Control API through the low-level
`memwing control ...` command family.

## Development

Backend setup:

```bash
uv sync
uv run pytest
uv run ruff check .
```

Run the backend locally:

```bash
# Start API and Memory Pipeline Runtime together
uv run memwing-runtime

# Or run the entrypoints separately
uv run memwing-api
uv run memwing-pipeline
```

CLI development:

```bash
uv run memwing quickstart --skip-openclaw --no-start
uv run memwing status --no-health
uv run memwing doctor --json
```

Control Plane frontend:

```bash
cd frontend
npm install
npm run dev
```

OpenClaw plugin development:

```bash
cd memwing/integrations/openclaw
npm install
npm run build
npm run smoke
```

## Project Status

MemWing is evolving quickly. The current implementation focuses on the v1 memory
runtime, OpenClaw integration, Lite setup, Control Plane APIs, benchmark support,
and local-first developer workflows.

## License

MemWing is released under the Apache License 2.0. See the root `LICENSE` file
for the full license text.
