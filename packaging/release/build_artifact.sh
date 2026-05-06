#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${MEMWING_VERSION:-0.1.0}"
OUT_DIR="$ROOT/dist/release"
ARTIFACT_DIR="$OUT_DIR/memwing-$VERSION"

rm -rf "$ARTIFACT_DIR"
mkdir -p \
  "$ARTIFACT_DIR/bin" \
  "$ARTIFACT_DIR/lib" \
  "$ARTIFACT_DIR/memwing-openclaw-plugin" \
  "$ARTIFACT_DIR/default-configs" \
  "$ARTIFACT_DIR/licenses"

if command -v uv >/dev/null 2>&1; then
  uv build --wheel --out-dir "$OUT_DIR/python"
else
  python -m build --wheel --outdir "$OUT_DIR/python"
fi

(
  cd "$ROOT/memwing/integrations/openclaw"
  npm run build:release
)

cp -R "$ROOT/memwing" "$ARTIFACT_DIR/lib/"
cat > "$ARTIFACT_DIR/bin/memwing" <<'EOF'
#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHONPATH="$ROOT/lib:$ROOT/lib/memwing/infrastructure/graph${PYTHONPATH:+:$PYTHONPATH}" \
  exec python3 -m memwing.cli "$@"
EOF
chmod +x "$ARTIFACT_DIR/bin/memwing"

cp -R "$ROOT/memwing/integrations/openclaw/dist/." "$ARTIFACT_DIR/memwing-openclaw-plugin/"
cp "$ROOT/memwing/integrations/openclaw/openclaw.plugin.json" "$ARTIFACT_DIR/memwing-openclaw-plugin/"
cp "$ROOT/pyproject.toml" "$ARTIFACT_DIR/default-configs/pyproject.toml"

cat > "$ARTIFACT_DIR/README.txt" <<EOF
MemWing $VERSION release artifact.

Install the Python wheel from dist/release/python, then run:

  memwing quickstart

The bundled memwing-openclaw-plugin directory is the prebuilt OpenClaw plugin artifact.
EOF

tar -C "$OUT_DIR" -czf "$OUT_DIR/memwing-$VERSION.tar.gz" "memwing-$VERSION"
echo "$OUT_DIR/memwing-$VERSION.tar.gz"
