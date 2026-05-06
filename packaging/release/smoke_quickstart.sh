#!/usr/bin/env sh
set -eu

PREFIX="${1:-${MEMWING_INSTALL_PREFIX:-$HOME/.local}}"
SMOKE_HOME="${MEMWING_SMOKE_HOME:-$(mktemp -d)}"

PATH="$PREFIX/bin:$PATH" \
MEMWING_HOME="$SMOKE_HOME" \
  memwing quickstart --profile lite --dry-run
