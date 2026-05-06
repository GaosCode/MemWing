from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_homebrew_formula_installs_release_artifact_without_placeholder_sha() -> None:
    formula = (ROOT / "packaging/homebrew/memwing.rb").read_text(encoding="utf-8")

    assert "REPLACE_WITH_RELEASE_SHA256" not in formula
    assert "virtualenv_install_with_resources" not in formula
    assert "sha256 :no_check" in formula
    assert 'prefix.install Dir["*"]' in formula
    assert "python@3.13" in formula
    assert 'artifact_python = (prefix/"PYTHON_MAJOR_MINOR").read.strip' in formula
    assert 'unless artifact_python == "3.13"' in formula
    assert '(prefix/"PYTHON_MAJOR_MINOR").write' not in formula
    assert '(prefix/"PYTHON_EXECUTABLE").write' not in formula


def test_release_artifact_bundles_python_dependencies_and_installs_to_prefix() -> None:
    build_script = (ROOT / "packaging/release/build_artifact.sh").read_text(encoding="utf-8")
    install_script = (ROOT / "packaging/install.sh").read_text(encoding="utf-8")

    assert '--target "$ARTIFACT_DIR/lib/python"' in build_script
    assert 'PYTHONPATH="$ROOT/lib/python:' in build_script
    assert 'PYTHON_BIN="${PYTHON_BIN:-python3.13}"' in build_script
    assert 'PYTHON_MAJOR_MINOR="$("$PYTHON_BIN" -c' in build_script
    assert 'PYTHON_BIN="${MEMWING_PYTHON:-python$PYTHON_MAJOR_MINOR}"' in build_script
    assert 'exec "$PYTHON_BIN" -m memwing.cli "$@"' in build_script
    assert 'printf "%s\\n" "$PYTHON_MAJOR_MINOR" > "$ARTIFACT_DIR/PYTHON_MAJOR_MINOR"' in build_script
    assert '"$ARTIFACT_DIR/memwing-openclaw-plugin/dist"' in build_script
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
    assert "python_major_minor=" in install_script
    assert 'python_bin="${MEMWING_PYTHON:-python$python_major_minor}"' in install_script
    assert 'cp -R "$tmp_dir/extract/memwing-$VERSION/." "$PREFIX/"' in install_script
