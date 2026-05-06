from __future__ import annotations

import json
from pathlib import Path

import pytest

from memwing.cli import main
from memwing.config_store import load_json_config


def test_memwing_config_set_get_unset_and_file_are_backed_by_user_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))

    with pytest.raises(SystemExit) as file_exit:
        main(["config", "file"])
    assert file_exit.value.code == 0
    config_path = Path(capsys.readouterr().out.strip())

    with pytest.raises(SystemExit) as set_exit:
        main(["config", "set", "api.port", "8123"])
    assert set_exit.value.code == 0
    assert load_json_config(config_path)["api"]["port"] == 8123
    capsys.readouterr()

    with pytest.raises(SystemExit) as get_exit:
        main(["config", "get", "api.port"])
    assert get_exit.value.code == 0
    assert capsys.readouterr().out.strip() == "8123"

    with pytest.raises(SystemExit) as unset_exit:
        main(["config", "unset", "api.port"])
    assert unset_exit.value.code == 0
    assert load_json_config(config_path)["api"] == {}


def test_memwing_start_print_env_uses_redacted_effective_runtime_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))

    with pytest.raises(SystemExit):
        main(["config", "set", "graph.neo4j.password", "secret-password"])
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_info:
        main(["start", "--profile", "lite", "--port", "8123", "--print-env"])

    assert exit_info.value.code == 0
    env = json.loads(capsys.readouterr().out)
    assert env["MEMWING_PROFILE"] == "lite"
    assert env["MEMWING_API_PORT"] == "8123"
    assert env["MEMWING_STORAGE_BACKEND"] == "sqlite"
    assert env["MEMWING_GRAPH_BACKEND"] == "disabled"
    assert env["MEMWING_EVIDENCE_BACKEND"] == "disabled"
    assert env["MEMWING_GRAPHITI_NEO4J_PASSWORD"] == "<redacted>"
    assert "DATABASE_URL" not in env


def test_memwing_quickstart_lite_initializes_config_layout_and_sqlite_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memwing_home = tmp_path / "home"
    monkeypatch.setenv("MEMWING_HOME", str(memwing_home))

    with pytest.raises(SystemExit) as exit_info:
        main(["quickstart", "--profile", "lite"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "profile: lite" in output
    assert (memwing_home / "memwing.json").exists()
    assert (memwing_home / "memwing.db").exists()
    assert (memwing_home / "evidence").is_dir()
    assert (memwing_home / "graph").is_dir()
