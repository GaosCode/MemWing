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

## Upgrade Procedure

1. Record the current upstream commit/tag in this file before replacing code.
2. Replace `memwing/infrastructure/graph/graphiti_core` from upstream.
3. Reapply the local changes listed above.
4. Confirm the import package remains `graphiti_core`.
5. Re-run boundary and adapter contract tests.
6. Update this file with any new local patches.

## Verification

- `pytest tests/unit/test_layer_boundaries.py`
- `pytest tests/integration/test_graphiti_adapter_contract.py`
- `pytest tests/integration/test_graph_write_worker.py`
- `pytest tests/integration/test_source_redaction.py`

Milestone 3 cannot be accepted if this file no longer matches the vendored
Graphiti source or omits a verifiable upstream reference.
