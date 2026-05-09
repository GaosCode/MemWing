from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_homebrew_formula_installs_release_artifact_without_placeholder_sha() -> None:
    formula = (ROOT / "packaging/homebrew/memwing.rb").read_text(encoding="utf-8")

    assert (
        "https://github.com/GaosCode/MemWing/releases/download/v0.1.6/"
        "memwing-0.1.6.tar.gz"
    ) in formula
    assert 'homepage "https://github.com/GaosCode/MemWing"' in formula
    assert "github.com/memwing/memwing" not in formula
    assert "REPLACE_WITH_RELEASE_SHA256" not in formula
    assert "REPLACE_WITH_V0_1_3_SHA256" not in formula
    assert "virtualenv_install_with_resources" not in formula
    assert "sha256 :no_check" not in formula
    assert 'libexec.install Dir["*"]' in formula
    assert 'export MEMWING_PYTHON="#{python}"' in formula
    assert 'exec "#{libexec}/bin/memwing" "$@"' in formula
    assert 'chmod 0755, bin/"memwing"' in formula
    assert "python@3.13" in formula
    assert 'artifact_python = (libexec/"PYTHON_MAJOR_MINOR").read.strip' in formula
    assert 'if artifact_python != "3.13"' in formula
    assert '(prefix/"PYTHON_MAJOR_MINOR").write' not in formula
    assert '(prefix/"PYTHON_EXECUTABLE").write' not in formula


def test_release_artifact_bundles_python_dependencies_and_installs_to_prefix() -> None:
    build_script = (ROOT / "packaging/release/build_artifact.sh").read_text(encoding="utf-8")
    install_script = (ROOT / "packaging/install.sh").read_text(encoding="utf-8")

    assert '--target "$ARTIFACT_DIR/lib/python"' in build_script
    assert 'PYTHONPATH="$ROOT/lib/python:' in build_script
    assert 'PYTHON_BIN="${PYTHON_BIN:-python3.13}"' in build_script
    assert 'VERSION="${MEMWING_VERSION:-0.1.6}"' in build_script
    assert 'PYTHON_MAJOR_MINOR="$("$PYTHON_BIN" -c' in build_script
    assert 'PYTHON_BIN="${MEMWING_PYTHON:-python$PYTHON_MAJOR_MINOR}"' in build_script
    assert 'exec "$PYTHON_BIN" -m memwing.cli "$@"' in build_script
    assert 'printf "%s\\n" "$PYTHON_MAJOR_MINOR" > "$ARTIFACT_DIR/PYTHON_MAJOR_MINOR"' in build_script
    assert '"$ARTIFACT_DIR/memwing-openclaw-plugin/dist"' in build_script
    assert (
        'cp "$ROOT/memwing/integrations/openclaw/package.json" '
        '"$ARTIFACT_DIR/memwing-openclaw-plugin/"'
    ) in build_script
    assert (
        'cp "$ROOT/memwing/integrations/openclaw/openclaw.plugin.json" '
        '"$ARTIFACT_DIR/memwing-openclaw-plugin/"'
    ) in build_script
    assert (
        'cp -R "$ROOT/memwing/integrations/openclaw/dist/." '
        '"$ARTIFACT_DIR/memwing-openclaw-plugin/dist/"'
    ) in build_script
    assert (
        'cp -R "$ROOT/memwing/integrations/openclaw/dist/." '
        '"$ARTIFACT_DIR/memwing-openclaw-plugin/"'
    ) not in build_script
    assert '"$ARTIFACT_DIR/control-plane"' in build_script
    assert 'cd "$ROOT/frontend"' in build_script
    assert "npm run build" in build_script
    assert 'cp -R "$ROOT/frontend/dist/." "$ARTIFACT_DIR/control-plane/"' in build_script
    assert 'cp "$ROOT/LICENSE" "$ARTIFACT_DIR/licenses/LICENSE"' in build_script
    assert 'VERSION="${MEMWING_VERSION:-0.1.6}"' in install_script
    assert "python_major_minor=" in install_script
    assert "https://github.com/GaosCode/MemWing/releases/download/v$VERSION" in install_script
    assert "github.com/memwing/memwing" not in install_script
    assert 'python_bin="${MEMWING_PYTHON:-python$python_major_minor}"' in install_script
    assert 'cp -R "$tmp_dir/extract/memwing-$VERSION/." "$PREFIX/"' in install_script
    assert 'expected_sha256="${MEMWING_ARTIFACT_SHA256:-}"' in install_script
    assert 'checksum_url="$url.sha256"' in install_script
    assert 'verify_sha256 "$tmp_dir/$artifact" "$expected_sha256"' in install_script
    assert install_script.index('verify_sha256 "$tmp_dir/$artifact" "$expected_sha256"') < (
        install_script.index('tar -xzf "$tmp_dir/$artifact"')
    )
    assert 'write_sha256 "$tar_path" "$tar_path.sha256"' in build_script
    assert 'tar_path="$OUT_DIR/memwing-$VERSION.tar.gz"' in build_script
    assert build_script.index("npm run build:release") < build_script.index("uv build --wheel")


def test_release_artifact_strips_local_build_metadata() -> None:
    build_script = (ROOT / "packaging/release/build_artifact.sh").read_text(encoding="utf-8")

    assert 'find "$ARTIFACT_DIR/lib/python" -type d -name "__pycache__"' in build_script
    assert 'find "$ARTIFACT_DIR/lib/python" -type f -name "*.pyc" -delete' in build_script
    assert (
        'find "$ARTIFACT_DIR/lib/python" -type f -path "*/memwing-*.dist-info/direct_url.json"'
        in build_script
    )
    assert 'find "$ARTIFACT_DIR/lib/python" -type d -name "sboms"' in build_script
    assert 'find "$ARTIFACT_DIR/lib/python" -type f -path "*/numpy/__config__.py"' in build_script
    assert "<redacted-build-path>" in build_script
    assert '-type f -name "direct_url.json"' in build_script
    assert 'local_path_scan_list="$OUT_DIR/local-path-scan-files.txt"' in build_script
    assert '-name "*.py"' in build_script
    assert '-name "*.json"' in build_script
    assert '-name "METADATA"' in build_script
    assert '-name "RECORD"' in build_script
    assert "/Users/|/private/tmp/|/var/folders|MemWing_development_docs" in build_script


def test_release_packaging_has_real_quickstart_smoke() -> None:
    smoke_script = (ROOT / "packaging/release/smoke_quickstart.sh").read_text(encoding="utf-8")

    assert "memwing quickstart --profile lite" in smoke_script
    assert "--dry-run" not in smoke_script
    assert "OPENCLAW_CLI=" in smoke_script
    assert "/healthz" in smoke_script
    assert "MEMWING_HOME=" in smoke_script
    assert 'PATH="$PREFIX/bin:$PATH"' in smoke_script
    assert 'plugins.slots.memory' in smoke_script
    assert '"config":{"nativeMemoryTools":true}' in smoke_script
    assert "MEMWING_CONTROL_PLANE_SMOKE_PORT" in smoke_script
    assert "memwing control-plane" in smoke_script
    assert '--api-base-url "http://127.0.0.1:$SMOKE_PORT"' in smoke_script
    assert 'http://127.0.0.1:$CONTROL_PLANE_PORT/' in smoke_script


def test_python_package_includes_openclaw_plugin_artifact() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'license = "Apache-2.0"' in pyproject
    assert 'license-files = ["LICENSE"]' in pyproject
    assert '"setuptools>=77.0.0"' in pyproject
    assert '[tool.setuptools.package-data]' in pyproject
    assert '"memwing.integrations.openclaw"' in pyproject
    assert '"package.json"' in pyproject
    assert '"openclaw.plugin.json"' in pyproject
    assert '"dist/**"' in pyproject
