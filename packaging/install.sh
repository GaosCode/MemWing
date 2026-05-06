#!/usr/bin/env sh
set -eu

VERSION="${MEMWING_VERSION:-0.1.1}"
PREFIX="${MEMWING_INSTALL_PREFIX:-$HOME/.local}"
BASE_URL="${MEMWING_RELEASE_BASE_URL:-https://github.com/GaosCode/MemWing/releases/download/v$VERSION}"

artifact="memwing-$VERSION.tar.gz"
url="$BASE_URL/$artifact"
checksum_url="$url.sha256"
expected_sha256="${MEMWING_ARTIFACT_SHA256:-}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

calculate_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
    return
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
    return
  fi
  echo "No SHA256 tool found. Install shasum or sha256sum." >&2
  exit 1
}

verify_sha256() {
  file="$1"
  expected="$2"
  actual="$(calculate_sha256 "$file")"
  if [ "$actual" != "$expected" ]; then
    echo "SHA256 mismatch for $artifact" >&2
    echo "expected: $expected" >&2
    echo "actual:   $actual" >&2
    exit 1
  fi
}

echo "Installing MemWing $VERSION"
echo "Download: $url"
echo "Install prefix: $PREFIX"
echo "This installer only writes MemWing release files. It does not modify OpenClaw or runtime state."

mkdir -p "$PREFIX"
curl -fsSL "$url" -o "$tmp_dir/$artifact"
if [ -z "$expected_sha256" ]; then
  echo "Checksum: $checksum_url"
  curl -fsSL "$checksum_url" -o "$tmp_dir/$artifact.sha256"
  expected_sha256="$(awk '{print $1}' "$tmp_dir/$artifact.sha256")"
fi
if [ -z "$expected_sha256" ]; then
  echo "Release artifact checksum is empty. Set MEMWING_ARTIFACT_SHA256." >&2
  exit 1
fi
verify_sha256 "$tmp_dir/$artifact" "$expected_sha256"
mkdir -p "$tmp_dir/extract"
tar -xzf "$tmp_dir/$artifact" -C "$tmp_dir/extract"
if [ ! -d "$tmp_dir/extract/memwing-$VERSION" ]; then
  echo "Release artifact does not contain memwing-$VERSION" >&2
  exit 1
fi
if [ ! -f "$tmp_dir/extract/memwing-$VERSION/PYTHON_MAJOR_MINOR" ]; then
  echo "Release artifact is missing PYTHON_MAJOR_MINOR" >&2
  exit 1
fi
python_major_minor="$(cat "$tmp_dir/extract/memwing-$VERSION/PYTHON_MAJOR_MINOR")"
python_bin="${MEMWING_PYTHON:-python$python_major_minor}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "MemWing $VERSION requires Python $python_major_minor for bundled native wheels." >&2
  echo "Install python$python_major_minor or set MEMWING_PYTHON to a compatible interpreter." >&2
  exit 1
fi
cp -R "$tmp_dir/extract/memwing-$VERSION/." "$PREFIX/"

echo "Installed. Add $PREFIX/bin to PATH if needed."
echo "Next: memwing quickstart"
