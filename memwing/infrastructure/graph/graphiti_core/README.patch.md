# Vendored Graphiti Patch Notes

This directory vendors Graphiti Core for MemWing's default graph backend.
MemWing keeps the upstream Python import package name as `graphiti_core` so the
vendored source can retain its internal imports without mechanical rewriting.

## Upstream

- Source package: `graphiti-core`
- Upstream repository: https://github.com/getzep/graphiti
- Upstream package version: `graphiti-core==0.28.2`
- Upstream commit: `9cdcc93`
- Vendored date: 2026-04-27
- License: Apache License 2.0, as declared in the vendored source file headers

## Local Changes

- Kept the upstream import package name: `graphiti_core`.
- Vendored the source under `memwing/infrastructure/graph/graphiti_core`.
- MemWing code must access this package only through
  `memwing/infrastructure/graph/graphiti_adapter.py`.
- Core, application, api, and worker layers must not import `graphiti_core`
  directly.
- Disabled upstream default provider client construction in `graphiti.py`.
  `Graphiti.__init__` now raises when `llm_client`, `embedder`, or
  `cross_encoder` is missing. MemWing must inject clients created from
  `memwing/infrastructure/llm` through `GraphitiAdapter`.
- Made `graphiti_core.__init__` lazily export `Graphiti` so MemWing wrapper
  unit tests can import Graphiti base interfaces without requiring database
  driver extras.
- Made `graphiti_core.cross_encoder.__init__` lazily export
  `OpenAIRerankerClient` so MemWing can import the cross-encoder base interface
  without loading provider/database extras.
- Added Kuzu `_database` tracking and clone support so Graphiti's shared
  `group_id` routing path works with the Kuzu driver.
- Wired `KuzuDriver.build_indices_and_constraints()` to the Kuzu graph
  maintenance operation so required FTS indices are created before write/search
  paths run.
- Created Kuzu FTS indices during `KuzuDriver.setup_schema()` because
  `Graphiti.add_episode()` performs edge search during first write and can
  reach FTS before callers have a separate migration hook.

## Upgrade Procedure

1. Record the current upstream commit/tag in this file before replacing code.
2. Replace `memwing/infrastructure/graph/graphiti_core` from upstream.
3. Reapply the local changes listed above.
4. Confirm the import package remains `graphiti_core`.
5. Re-run boundary and adapter contract tests.
6. Update this file with any new local patches.

## Verification

- `pytest tests/unit/test_layer_boundaries.py`
- `pytest tests/contracts/test_graphiti_model_boundary.py`
- `pytest tests/unit/test_graphiti_adapter.py`
- `pytest tests/integration/test_graphiti_adapter_contract.py`
- `pytest tests/integration/test_graph_write_worker.py`
- `pytest tests/integration/test_source_redaction.py`

Milestone 3 cannot be accepted if this file no longer matches the vendored
Graphiti source or omits a verifiable upstream reference.
