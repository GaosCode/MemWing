#!/usr/bin/env sh
set -eu

VERSION="${MEMWING_VERSION:-0.1.0}"
PREFIX="${MEMWING_INSTALL_PREFIX:-$HOME/.local}"
BASE_URL="${MEMWING_RELEASE_BASE_URL:-https://github.com/memwing/memwing/releases/download/v$VERSION}"

artifact="memwing-$VERSION.tar.gz"
url="$BASE_URL/$artifact"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

echo "Installing MemWing $VERSION"
echo "Download: $url"
echo "Install prefix: $PREFIX"
echo "This installer only writes MemWing release files. It does not modify OpenClaw or runtime state."

mkdir -p "$PREFIX"
curl -fsSL "$url" -o "$tmp_dir/$artifact"
mkdir -p "$tmp_dir/extract"
tar -xzf "$tmp_dir/$artifact" -C "$tmp_dir/extract"
if [ ! -d "$tmp_dir/extract/memwing-$VERSION" ]; then
  echo "Release artifact does not contain memwing-$VERSION" >&2
  exit 1
fi
cp -R "$tmp_dir/extract/memwing-$VERSION/." "$PREFIX/"

echo "Installed. Add $PREFIX/bin to PATH if needed."
echo "Next: memwing quickstart"
