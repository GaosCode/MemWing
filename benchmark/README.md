# MemWing Benchmark

`benchmark/` contains the MemWing benchmark harness for evaluating OpenClaw native
memory behavior in collaboration scenarios. It focuses on two questions:

- Can existing long-term memory be retrieved with the expected facts?
- Can live collaboration messages be converted into durable memory artifacts?

This directory is designed to be runnable from a local checkout. Public commits
must not include personal paths, private chat identifiers, API keys, raw run logs,
or organization-specific credentials.

## Contents

```text
benchmark/
  config.example.json
  datasets/
  memwing_benchmark/
  reports/
  runs/
  tests/
```

- `config.example.json`: template for local configuration.
- `datasets/`: benchmark cases and preseed files.
- `memwing_benchmark/`: CLI, adapters, evaluators, metrics, and report generation.
- `reports/`: curated benchmark reports safe to review and commit.
- `runs/`: generated run artifacts. This directory is ignored except for
  `runs/.gitkeep`.
- `tests/`: unit and dry-run coverage for the harness.

## Prerequisites

- Python 3.11 or newer.
- `uv` for dependency management.
- A local OpenClaw checkout when running OpenClaw-native tests.
- `pnpm` and OpenClaw CLI dependencies installed in the OpenClaw checkout.
- A judge model API key when running retrieval/write evaluation.
- Lark/Feishu CLI login and bot permissions when running live tests.

## Quick Start

Run all commands from this directory unless noted otherwise:

```bash
cd benchmark
uv sync --all-extras
uv run pytest
```

Create a local config file:

```bash
cp config.example.json config.local.json
```

`config.local.json` is ignored by git and is the only place where local paths,
API keys, bot IDs, and chat IDs should be stored.

Common commands:

```bash
# Single-case retrieval evaluation.
uv run memwing-benchmark --config config.local.json --mode retrieval --case-id bs001 --yes

# Batch retrieval evaluation.
uv run memwing-benchmark --config config.local.json --mode retrieval --batch --yes

# Batch write ingest. Sends seed messages to a live chat.
uv run memwing-benchmark --config config.local.json --mode write --phase ingest --batch --live --yes

# Batch write evaluation. Scores the current OpenClaw workspace memory files.
uv run memwing-benchmark --config config.local.json --mode write --phase evaluate --batch --yes
```

## Configuration

Use `config.example.json` as the starting point and replace every placeholder in
`config.local.json`:

```json
{
  "judge": {
    "provider": "volcengine_ark",
    "api_key": "",
    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "model": "YOUR_MODEL_ID",
    "temperature": 0
  },
  "paths": {
    "openclaw_repo_dir": "/absolute/path/to/openclaw",
    "memwing_repo_dir": "/absolute/path/to/MemWing",
    "runs_dir": "/absolute/path/to/MemWing/benchmark/runs"
  },
  "feishu": {
    "cli_bin": "lark-cli",
    "bot_app_id": "YOUR_BOT_APP_ID",
    "bot_open_id": "YOUR_BOT_OPEN_ID",
    "bot_name": "YOUR_BOT_NAME",
    "mention_text": "<at user_id=\"YOUR_BOT_OPEN_ID\">YOUR_BOT_NAME</at>",
    "chat_id": "",
    "seed_chat_id": "",
    "probe_chat_id": "",
    "create_chat_if_missing": false,
    "chat_name_prefix": "MemWing Bench"
  },
  "openclaw": {
    "agent_id": "main",
    "trajectory_dir": "",
    "configure_allowlist": false,
    "restart_gateway": false,
    "workspace_dir": ""
  },
  "memwing": {
    "base_url": "http://127.0.0.1:8000",
    "agent_id": "main",
    "workspace_id": "workspace_001",
    "session_id": "memwing-benchmark",
    "project_memory_space_id": "project_001",
    "group_id": "benchmark_group",
    "thread_id": "benchmark_thread",
    "shared_group_id": "",
    "safe_mode": false,
    "ingest_timeout_seconds": 30,
    "search_timeout_seconds": 30,
    "settle_seconds": 2,
    "poll_interval_seconds": 2,
    "poll_timeout_seconds": 60
  }
}
```

Configuration notes:

- `judge.api_key` is required for retrieval judge, answer judge, and write judge.
- `paths.openclaw_repo_dir` must point to the local OpenClaw checkout.
- `paths.runs_dir` controls where generated run artifacts are written.
- `feishu.chat_id` is used by live write ingest when an existing chat is reused.
- `feishu.seed_chat_id` and `feishu.probe_chat_id` can be used to separate live
  retrieval seed and probe chats.
- `feishu.create_chat_if_missing=true` allows the harness to create test chats.
- `openclaw.configure_allowlist=true` allows the harness to update OpenClaw's
  Lark/Feishu chat allowlist.
- `openclaw.restart_gateway=true` allows the harness to restart OpenClaw gateway
  after configuration changes.
- `memwing.base_url` is required for the MemWing HTTP backend and should point
  at the MemWing server under test.
- `memwing.project_memory_space_id` is the Project Memory Space scope hint used
  for benchmark Source Event ingest and memory search.
- `memwing.group_id`, `memwing.thread_id`, and `memwing.shared_group_id` are
  local scope hints. Do not commit private platform chat, group, thread, or
  shared-group values.
- `memwing.safe_mode` documents the intended local test posture only. Effective
  Scope and Safe Mode remain server-authoritative.
- `memwing.ingest_timeout_seconds`, `memwing.search_timeout_seconds`,
  `memwing.settle_seconds`, `memwing.poll_interval_seconds`, and
  `memwing.poll_timeout_seconds` control local benchmark HTTP and readiness
  timing.

Do not commit `config.local.json`, `.env`, generated run records, chat exports,
or raw memory snapshots unless they have been reviewed and sanitized.

## Dataset Format

Benchmark cases live under `datasets/`.

```text
datasets/
  bs001.json
  fu001.json
  fu002.json
  lt001.json
  lt002.json
  lt003.json
  lt004.json
  lt005.json
  lt006.json
  tc001.json
  preseed/
```

Each case file is independent:

- `seed_messages`: ordered collaboration messages used as the source material.
- `expected_memory_items`: gold facts that should be written to durable memory.
- `probes`: retrieval questions used to test whether gold facts can be found.
- `datasets/preseed/<case_id>.md`: OpenClaw-compatible plaintext generated from
  the full seed conversation for retrieval preseed tests.

Preseed files should preserve both signal and noise from the original seed
conversation. Do not build preseed files from `expected_memory_items` only,
because that turns retrieval into a clean-answer lookup test.

## OpenClaw Setup

Run these commands from the OpenClaw checkout:

```bash
pnpm openclaw memory status --deep --json --agent main
pnpm openclaw config get tools --json
```

The OpenClaw agent must have access to memory search and write tools. A typical
tool profile includes:

```json
{
  "profile": "coding",
  "allow": ["memory_search", "memory_get", "write"]
}
```

After changing OpenClaw configuration, restart the gateway:

```bash
pnpm openclaw gateway restart
```

A basic memory search smoke test:

```bash
pnpm openclaw memory search \
  --query "Who owns the dashboard migration project?" \
  --max-results 5 \
  --json \
  --agent main
```

## CLI Options

| Option | Default | Description |
|---|---|---|
| `--config` | `config.example.json` | Config file path. Use `config.local.json` for real runs. |
| `--backend` | `openclaw-native` | Benchmark backend: `openclaw-native` or `memwing`. MemWing currently supports retrieval mode through the HTTP API. |
| `--mode` | `retrieval` | Run mode: `retrieval` or `write`. |
| `--phase` | `full` | Write mode phase: `full`, `ingest`, or `evaluate`. |
| `--cases` | `datasets` | Case file or directory. |
| `--case-id` | empty | Run a single case by ID. |
| `--batch` | false | Run all cases under `--cases`. |
| `--live` | false | Enable live Lark/Feishu and OpenClaw interactions. |
| `--chat-id` | empty | Override `feishu.chat_id`. |
| `--create-chat` | false | Create test chats through the Lark/Feishu CLI. |
| `--configure-openclaw` | false | Update OpenClaw chat allowlist/configuration. |
| `--restart-gateway` | false | Restart OpenClaw gateway. |
| `--yes` | false | Skip side-effect confirmation prompts. |
| `--runs-dir` | config value | Override generated output directory. |
| `--trajectory-dir` | config value | Override OpenClaw trajectory directory. |
| `--message-interval-seconds` | `2.0` | Delay between live seed messages. |
| `--settle-seconds` | `2.0` | Delay after live seed sending. |
| `--reply-timeout-seconds` | `120.0` | Timeout while waiting for live probe replies. |
| `--memory-poll-interval-seconds` | `20.0` | Poll interval for memory file changes. |
| `--memory-timeout-seconds` | `60.0` | Timeout for memory file change polling. |

Runtime constraints:

- Non-batch runs must load exactly one case. Use `--case-id` or pass one case file.
- `retrieval --live --batch` is not supported.
- `write --phase ingest` and `write --phase full` require `--live`.
- `write --phase evaluate` reads local OpenClaw memory files and must not use
  `--live`.

## Retrieval Mode

Retrieval mode tests whether OpenClaw can retrieve the expected facts after
memory already exists and has been indexed.

### Single Case

```bash
uv run memwing-benchmark \
  --config config.local.json \
  --mode retrieval \
  --case-id bs001 \
  --yes
```

The harness:

1. Loads `datasets/bs001.json`.
2. Writes the full case preseed to `memory/memwing-benchmark-preseed.md` in the
   active OpenClaw workspace.
3. Runs `openclaw memory index --force --agent <agent_id>`.
4. Runs `openclaw memory search` for each probe.
5. Uses the judge model to compute retrieval recall.

### Batch

```bash
uv run memwing-benchmark \
  --config config.local.json \
  --mode retrieval \
  --batch \
  --yes
```

Batch retrieval runs each case in isolation by replacing the same preseed file,
rebuilding the index, and then evaluating that case's probes. Existing memory in
the active OpenClaw workspace can still affect results, so use an isolated
workspace for reproducible public reports.

### Live Cross-Chat

```bash
uv run memwing-benchmark \
  --config config.local.json \
  --mode retrieval \
  --case-id bs001 \
  --live \
  --create-chat \
  --configure-openclaw \
  --restart-gateway \
  --yes
```

Live cross-chat retrieval uses separate seed and probe chats. The seed chat
injects facts, the probe chat asks questions, and the benchmark checks whether
durable memory can bridge the two chats.

This mode creates or modifies external resources, updates OpenClaw
configuration, may restart OpenClaw gateway, and should only be run with a
sanitized local config.

## Write Mode

Write mode tests whether live collaboration messages become durable memory.

Recommended batch workflow:

1. Run `write --phase ingest` to send seed messages.
2. Wait until OpenClaw logs or memory files show that writing has completed.
3. Run `write --phase evaluate` to score the current workspace memory files.

### Batch Ingest

```bash
uv run memwing-benchmark \
  --config config.local.json \
  --mode write \
  --phase ingest \
  --batch \
  --live \
  --chat-id YOUR_CHAT_ID \
  --yes
```

To create a test chat and configure OpenClaw automatically:

```bash
uv run memwing-benchmark \
  --config config.local.json \
  --mode write \
  --phase ingest \
  --batch \
  --live \
  --create-chat \
  --configure-openclaw \
  --restart-gateway \
  --yes
```

Ingest behavior:

- Sends all case `seed_messages` to one live ingest chat.
- Does not force OpenClaw to flush memory.
- Does not wait for or judge memory writes.
- Produces run records that should be treated as private until reviewed.

### Batch Evaluate

```bash
uv run memwing-benchmark \
  --config config.local.json \
  --mode write \
  --phase evaluate \
  --batch \
  --yes
```

Evaluate behavior:

- Sends no live messages.
- Reads the current OpenClaw workspace.
- Collects `MEMORY.md`, `DREAMS.md`, and `memory/*.md`.
- Uses the judge model to score each case's `expected_memory_items`.
- Emits debug logs to stderr for snapshot size, case progress, judge duration,
  and judge availability.

If the judge times out or returns unparsable JSON, write metrics for that case
may be `null`. A `null` score means judge unavailable; it does not prove that
OpenClaw failed to write memory.

### Single-Case Full Run

```bash
uv run memwing-benchmark \
  --config config.local.json \
  --mode write \
  --phase full \
  --case-id bs001 \
  --live \
  --chat-id YOUR_CHAT_ID \
  --yes
```

`full` sends one case, polls for memory changes, and evaluates immediately. It
is useful for debugging a single case, but batch experiments should prefer the
separate ingest/evaluate workflow because OpenClaw memory writing is asynchronous.

## Manual Preseed Smoke Test

Use an isolated OpenClaw workspace when debugging retrieval manually:

```bash
export MEMWING_RETRIEVAL_WORKSPACE=/absolute/path/to/tmp/memwing-retrieval-workspace
mkdir -p "$MEMWING_RETRIEVAL_WORKSPACE/memory"

cd /absolute/path/to/openclaw
pnpm openclaw config set agents.defaults.workspace "$MEMWING_RETRIEVAL_WORKSPACE"
```

Copy a preseed file from this repository:

```bash
cd /absolute/path/to/MemWing/benchmark
cp datasets/preseed/bs001.md "$MEMWING_RETRIEVAL_WORKSPACE/memory/memwing-bs001.md"
```

Rebuild the index and search:

```bash
cd /absolute/path/to/openclaw

pnpm openclaw memory index --force --agent main

pnpm openclaw memory search \
  --query "Who owns the dashboard migration project?" \
  --max-results 5 \
  --min-score 0 \
  --json \
  --agent main
```

Restore the previous OpenClaw workspace after the smoke test:

```bash
pnpm openclaw config set agents.defaults.workspace /absolute/path/to/original/workspace
pnpm openclaw gateway restart
```

## Run Outputs

Each run writes artifacts under:

```text
runs/<run_mode>/<yyyymmdd>/<run_id>/
  config.json
  normalized.jsonl
  scores.json
  report.md
  raw/
```

Common `run_mode` values:

| run_mode | Source command |
|---|---|
| `retrieval` | `--mode retrieval` |
| `retrieval-batch` | `--mode retrieval --batch` |
| `write` | `--mode write --phase full` |
| `write-ingest-batch` | `--mode write --phase ingest --batch` |
| `write-evaluate-batch` | `--mode write --phase evaluate --batch` |

Generated files:

- `config.json`: sanitized run configuration. API keys, Feishu bot identifiers,
  Feishu chat identifiers, MemWing group/thread hints, and URL credentials are
  removed; paths and non-secret endpoints may still reveal local context.
- `normalized.jsonl`: structured probe or case results.
- `scores.json`: aggregate metrics.
- `report.md`: human-readable report for review.
- `raw/records.json`: raw Lark/Feishu, OpenClaw, judge, trajectory, and debug
  records.

Review and sanitize generated reports before committing them. Do not commit raw
records that contain chat IDs, message contents, workspace paths, tokens, or
customer data.

## Metrics

Retrieval metrics:

- `retrieval_recall_at_1/3/5`: whether top-k retrieval results contain the gold
  facts needed to answer the probe.
- `retrieval_empty_rate`: share of probes with no retrieval results.
- `avg_retrieval_result_count`: average number of returned results per probe.
- `avg_retrieval_top_score`: average OpenClaw top-1 combined score.
- `avg_retrieval_top_vector_score`: average OpenClaw top-1 vector score.
- `avg_retrieval_top_text_score`: average OpenClaw top-1 text score.
- `avg_memory_search_latency_ms`: wall-clock latency measured by the benchmark
  harness around `openclaw memory search`.

Write metrics:

- `write_recall`: matched expected memory count divided by expected memory count.
- `write_precision`: judge-estimated share of written facts that are correct.
- `write_changed_file_count`: number of non-empty memory artifacts considered by
  the evaluator.
- `write_written_claim_count`: judge-estimated count of written factual claims.
- `write_noise_count`, `write_wrong_count`, `write_stale_count`: judge-estimated
  noise, incorrect, and stale fact counts.

Metric caveats:

- OpenClaw `memory search --json` returns search results, not stable internal
  agent debug timing.
- `avg_memory_search_latency_ms` is measured outside OpenClaw and should not be
  treated as internal OpenClaw latency.
- Write judge results depend on model availability and JSON parseability. Review
  `raw/records.json` and memory artifacts when a score is missing or surprising.

## Known Limitations

- `--backend memwing` currently supports retrieval mode only; MemWing write mode
  remains a later checkpoint.
- Live retrieval does not support batch mode.
- Write ingest does not verify that asynchronous memory writing has completed.
- Write evaluate reads the current OpenClaw workspace; verify the workspace before
  running it.
- Retrieval and write evaluation require a configured judge API key.
- Missing trajectory data does not fail the run, but reports record it as missing.
- Generated `runs/*` artifacts are ignored by git and should remain local unless
  explicitly reviewed and sanitized.

## Public Commit Checklist

Before committing benchmark documentation or reports:

- Remove personal usernames, home directories, workspace paths, chat IDs, Open
  IDs, app IDs, API keys, tokens, and private model endpoints.
- Replace local machine paths with relative paths or `/absolute/path/to/...`
  placeholders.
- Keep `config.local.json`, `.env`, run artifacts, raw logs, and unsanitized
  memory snapshots out of git.
- Prefer curated summaries under `reports/` over raw `runs/` outputs.
- Run tests after changing benchmark code:

```bash
cd benchmark
uv run pytest
```
