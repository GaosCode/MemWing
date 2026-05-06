#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${MEMWING_VERSION:-0.1.0}"
OUT_DIR="$ROOT/dist/release"
ARTIFACT_DIR="$OUT_DIR/memwing-$VERSION"
PYTHON_BIN="${PYTHON_BIN:-python3.13}"
PYTHON_MAJOR_MINOR="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_EXECUTABLE_NAME="python$PYTHON_MAJOR_MINOR"

write_sha256() {
  local file="$1"
  local output="$2"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}' > "$output"
    return
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}' > "$output"
    return
  fi
  echo "No SHA256 tool found. Install shasum or sha256sum." >&2
  exit 1
}

rm -rf "$ARTIFACT_DIR"
mkdir -p \
  "$ARTIFACT_DIR/bin" \
  "$ARTIFACT_DIR/control-plane" \
  "$ARTIFACT_DIR/lib" \
  "$ARTIFACT_DIR/memwing-openclaw-plugin/dist" \
  "$ARTIFACT_DIR/default-configs" \
  "$ARTIFACT_DIR/licenses"

(
  cd "$ROOT/frontend"
  npm run build
)

(
  cd "$ROOT/memwing/integrations/openclaw"
  npm run build:release
)

if command -v uv >/dev/null 2>&1; then
  uv build --wheel --out-dir "$OUT_DIR/python"
else
  "$PYTHON_BIN" -m build --wheel --outdir "$OUT_DIR/python"
fi
wheel="$(find "$OUT_DIR/python" -maxdepth 1 -name 'memwing-*.whl' -print | sort | tail -n 1)"
if [[ -z "$wheel" ]]; then
  echo "MemWing wheel was not built" >&2
  exit 1
fi
"$PYTHON_BIN" -m pip install --upgrade --target "$ARTIFACT_DIR/lib/python" "$wheel"

cat > "$ARTIFACT_DIR/bin/memwing" <<'EOF'
#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON_MAJOR_MINOR="$(cat "$ROOT/PYTHON_MAJOR_MINOR")"
PYTHON_BIN="${MEMWING_PYTHON:-python$PYTHON_MAJOR_MINOR}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "MemWing requires Python $PYTHON_MAJOR_MINOR for this artifact. Set MEMWING_PYTHON to a compatible interpreter." >&2
  exit 1
fi
PYTHONPATH="$ROOT/lib/python:$ROOT/lib/python/memwing/infrastructure/graph${PYTHONPATH:+:$PYTHONPATH}" \
  exec "$PYTHON_BIN" -m memwing.cli "$@"
EOF
chmod +x "$ARTIFACT_DIR/bin/memwing"
printf "%s\n" "$PYTHON_MAJOR_MINOR" > "$ARTIFACT_DIR/PYTHON_MAJOR_MINOR"
printf "%s\n" "$PYTHON_EXECUTABLE_NAME" > "$ARTIFACT_DIR/PYTHON_EXECUTABLE"

cp "$ROOT/memwing/integrations/openclaw/openclaw.plugin.json" "$ARTIFACT_DIR/memwing-openclaw-plugin/"
cp -R "$ROOT/memwing/integrations/openclaw/dist/." "$ARTIFACT_DIR/memwing-openclaw-plugin/dist/"
cp -R "$ROOT/frontend/dist/." "$ARTIFACT_DIR/control-plane/"
cp "$ROOT/LICENSE" "$ARTIFACT_DIR/licenses/LICENSE"
cp "$ROOT/pyproject.toml" "$ARTIFACT_DIR/default-configs/pyproject.toml"

cat > "$ARTIFACT_DIR/README.txt" <<EOF
MemWing $VERSION release artifact.

Install this artifact by copying its contents to an install prefix, then run:

  memwing quickstart

The artifact includes Python $PYTHON_MAJOR_MINOR runtime dependencies under
lib/python and the prebuilt OpenClaw plugin under memwing-openclaw-plugin.
EOF

tar_path="$OUT_DIR/memwing-$VERSION.tar.gz"
tar -C "$OUT_DIR" -czf "$tar_path" "memwing-$VERSION"
write_sha256 "$tar_path" "$tar_path.sha256"
echo "$tar_path"
